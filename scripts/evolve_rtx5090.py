"""Generational search on the local RTX 5090, writing to artifacts/rtx5090-local/generations/.

The flat random search in scripts/train_rtx5090.py reached a plateau: 600 candidates
bought 0.8% over the previous best, and the top ten sat within 0.49% of each other.
So this one searches differently — it keeps the best of each generation, breeds them,
and stops on its own once a generation stops improving.

Two deliberate changes to the space being searched:

* Three families compete, not one. Codex's flat search had gradient boosting winning
  on CPU (0.17268) while the MLP search reached 0.16398, so neither family should be
  assumed better in advance; let selection decide.
* Bias correction is a gene. The January holdout of the current production model shows
  bias +0.081 — a systematic overestimate worth more than any architecture tweak.
  Candidates may learn a constant offset on validation and carry it.

    python -m scripts.evolve_rtx5090                       # run until it plateaus
    python -m scripts.evolve_rtx5090 --population 64 --generations 12
    python -m scripts.evolve_rtx5090 report                # table of generations

January 2026 stays out: the search pack carries November-December 2025 only, and the
run refuses to start if that ever changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from src.data import ROOT
from src.model import FeatureRegressor, fit_mlp, metrics
from scripts.train_rtx5090 import DESTINATION as LOCAL_ROOT, load_pack

GENERATIONS = LOCAL_ROOT / "generations"
SEED = 20260923

HIDDEN_CHOICES = [
    (64, 32), (128, 64, 32), (256, 128, 64), (512, 256, 128),
    (512, 512, 256, 128), (1024, 512, 256), (256, 256, 128, 64),
]


def random_candidate(rng: random.Random) -> dict:
    family = rng.choice(["mlp", "mlp", "boost", "extra_trees"])  # MLP leads so far
    shared = {
        "family": family,
        "features": rng.choice(["point", "trajectory"]),
        "bias_correction": rng.choice([True, False]),
    }
    if family == "mlp":
        return shared | {
            "hidden": list(rng.choice(HIDDEN_CHOICES)),
            "loss_name": rng.choice(["mae", "mae", "huber", "mse"]),
            "learning_rate": rng.choice([0.0002, 0.0003, 0.0005, 0.0007, 0.001, 0.002]),
            "weight_decay": rng.choice([0.001, 0.005, 0.01, 0.02, 0.05]),
            "batch_size": rng.choice([512, 1024, 2048, 4096]),
            "seed": rng.randrange(1, 10_000),
            "epochs": 500,
            "patience": rng.choice([30, 50, 80]),
        }
    if family == "boost":
        return shared | {
            "loss": rng.choice(["absolute_error", "absolute_error", "squared_error"]),
            "max_leaf_nodes": rng.choice([7, 15, 31, 63, 127]),
            "max_iter": rng.choice([250, 500, 900]),
            "learning_rate": rng.choice([0.02, 0.05, 0.08]),
            "l2_regularization": rng.choice([0.0, 1.0, 10.0]),
            "min_samples_leaf": rng.choice([20, 60, 150]),
        }
    return shared | {
        "n_estimators": rng.choice([300, 600]),
        "max_depth": rng.choice([12, 20, 30, None]),
        "min_samples_leaf": rng.choice([2, 8, 30]),
        "max_features": rng.choice([0.5, 0.8, 1.0]),
    }


def breed(mother: dict, father: dict, rng: random.Random) -> dict:
    """Uniform crossover between same-family parents, then mutate a couple of genes."""
    if mother["family"] != father["family"]:
        father = mother
    child = {key: rng.choice([mother[key], father.get(key, mother[key])]) for key in mother}
    fresh = random_candidate(rng)
    for key in rng.sample(sorted(child), k=min(2, len(child))):
        if key in ("family", "hidden") and key == "family":
            continue
        if key in fresh:
            child[key] = fresh[key]
    if child["family"] == "mlp":
        child["seed"] = rng.randrange(1, 10_000)  # never re-run an identical network
    return child


def fingerprint(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


def build(config: dict, x_train, y_train, x_valid, y_valid, device: str):
    parameters = {k: v for k, v in config.items() if k not in {"family", "features", "bias_correction"}}
    if config["family"] == "mlp":
        return fit_mlp(x_train, y_train, x_valid, y_valid, device=device, **parameters)
    if config["family"] == "boost":
        model = HistGradientBoostingRegressor(early_stopping=False, random_state=42, **parameters)
    else:
        model = ExtraTreesRegressor(n_jobs=4, random_state=42, **parameters)
    model.fit(x_train, y_train)
    return model, {"device": "cpu", "family": config["family"]}


def evaluate_shard(generation: int, shard: int, shards: int, device: str) -> None:
    protocol, train, valid = load_pack()
    folder = GENERATIONS / f"gen_{generation:02d}"
    population = json.loads((folder / "population.json").read_text())
    for index, config in enumerate(population):
        if index % shards != shard:
            continue
        digest = fingerprint(config)
        report = folder / f"{digest}.json"
        if report.exists():
            continue
        columns = protocol["point_features"] if config["features"] == "point" else protocol["features"]
        x_train = train[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
        x_valid = valid[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
        started = time.monotonic()
        try:
            with threadpool_limits(limits=4):
                model, details = build(config, x_train, train.power, x_valid, valid.power, device)
        except (RuntimeError, ValueError, MemoryError) as error:
            report.write_text(json.dumps({"config": config, "error": str(error)[:300]}) + "\n")
            continue
        model = FeatureRegressor(model, columns)
        prediction = model.predict(x_valid)
        offset = 0.0
        if config.get("bias_correction"):
            # A single constant, learned on validation only; the holdout never sees it fitted.
            offset = float(np.median(valid.power.to_numpy() - prediction))
            prediction = np.clip(prediction + offset, 0.0, 1.0)
        score = metrics(valid.power, prediction)
        info = {
            "digest": digest,
            "generation": generation,
            "config": config,
            "metrics": score,
            "bias_offset": round(offset, 5),
            "fit": details,
            "seconds": round(time.monotonic() - started, 2),
        }
        joblib.dump({"model": model, "info": info, "bias_offset": offset},
                    folder / f"{digest}.joblib", compress=3)
        np.save(folder / f"{digest}.predictions.npy", prediction)
        report.write_text(json.dumps(info, indent=2) + "\n")
        print(f"gen{generation} {digest} {config['family']:12s} mae {score['mae']:.5f} "
              f"({info['seconds']:.1f}s)", flush=True)


def collect(generation: int) -> list[dict]:
    folder = GENERATIONS / f"gen_{generation:02d}"
    rows = [json.loads(path.read_text()) for path in folder.glob("*.json")
            if path.name != "population.json"]
    done = [row for row in rows if "metrics" in row]
    done.sort(key=lambda row: row["metrics"]["mae"])
    return done


def evolve(population_size: int, generations: int, shards: int, device: str,
           elite: int, plateau: float, patience: int) -> None:
    load_pack()  # fail early if the pack is missing or contains January
    GENERATIONS.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    history, best_so_far, stale = [], float("inf"), 0
    parents: list[dict] = []

    for generation in range(generations):
        folder = GENERATIONS / f"gen_{generation:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        if not parents:
            population = [random_candidate(rng) for _ in range(population_size)]
        else:
            population = [dict(parent) for parent in parents[:elite]]
            while len(population) < population_size:
                mother, father = rng.choice(parents), rng.choice(parents)
                population.append(breed(mother, father, rng))
        (folder / "population.json").write_text(json.dumps(population, indent=2) + "\n")

        started = time.monotonic()
        processes = [
            subprocess.Popen(
                [sys.executable, "-m", "scripts.evolve_rtx5090", "shard",
                 "--generation", str(generation), "--shard", str(shard),
                 "--shards", str(shards), "--device", device],
                cwd=ROOT,
                stdout=(folder / f"shard_{shard}.log").open("w"),
                stderr=subprocess.STDOUT,
            )
            for shard in range(shards)
        ]
        peak_load, peak_memory = 0, 0
        while any(process.poll() is None for process in processes):
            time.sleep(5)
            try:
                raw = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10,
                ).stdout.strip().splitlines()[0]
                load, memory = (int(value) for value in raw.split(","))
                peak_load, peak_memory = max(peak_load, load), max(peak_memory, memory)
            except Exception:
                pass

        done = collect(generation)
        if not done:
            raise SystemExit(f"Generation {generation}: every candidate failed, see {folder}")
        best = done[0]["metrics"]["mae"]
        gain = (best_so_far - best) / best_so_far * 100 if np.isfinite(best_so_far) else float("inf")
        families = {}
        for row in done[:elite]:
            families[row["config"]["family"]] = families.get(row["config"]["family"], 0) + 1
        record = {
            "generation": generation,
            "evaluated": len(done),
            "failed": population_size - len(done),
            "best_mae": best,
            "median_mae": float(np.median([row["metrics"]["mae"] for row in done])),
            "gain_percent": None if not np.isfinite(gain) else round(gain, 3),
            "elite_families": families,
            "seconds": round(time.monotonic() - started, 1),
            "peak_gpu_utilisation_percent": peak_load,
            "peak_gpu_memory_mib": peak_memory,
        }
        history.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)

        stale = 0 if np.isfinite(gain) and gain > plateau else stale + 1
        best_so_far = min(best_so_far, best)
        parents = [row["config"] for row in done[: max(elite, population_size // 4)]]
        write_history(history, best_so_far)
        if stale >= patience:
            print(f"plateau: {stale} generations without a gain above {plateau}%", flush=True)
            break

    write_history(history, best_so_far)


def write_history(history: list[dict], best: float) -> None:
    (GENERATIONS / "history.json").write_text(
        json.dumps({"seed": SEED, "best_mae": best, "generations": history}, indent=2) + "\n"
    )


def report() -> None:
    path = GENERATIONS / "history.json"
    if not path.exists():
        raise SystemExit(f"No run yet: {path} is missing")
    data = json.loads(path.read_text())
    print(f"{'gen':>4}{'best mae':>11}{'median':>10}{'gain %':>9}{'sec':>7}{'gpu %':>7}  elite families")
    for row in data["generations"]:
        gain = "" if row["gain_percent"] is None else f"{row['gain_percent']:+.2f}"
        families = ", ".join(f"{k}×{v}" for k, v in row["elite_families"].items())
        print(f"{row['generation']:>4}{row['best_mae']:>11.5f}{row['median_mae']:>10.5f}"
              f"{gain:>9}{row['seconds']:>7.0f}{row['peak_gpu_utilisation_percent']:>7}  {families}")
    print(f"\nbest overall: {data['best_mae']:.5f}")

    everything = []
    for folder in sorted(GENERATIONS.glob("gen_*")):
        everything.extend(collect(int(folder.name.split("_")[1])))
    everything.sort(key=lambda row: row["metrics"]["mae"])
    if everything:
        pd.DataFrame(
            [
                {
                    "digest": row["digest"], "generation": row["generation"],
                    "mae": row["metrics"]["mae"], "rmse": row["metrics"]["rmse"],
                    "family": row["config"]["family"], "features": row["config"]["features"],
                    "bias_correction": row["config"].get("bias_correction"),
                    "bias_offset": row.get("bias_offset"), "seconds": row["seconds"],
                    "config": json.dumps(row["config"], sort_keys=True),
                }
                for row in everything
            ]
        ).to_csv(GENERATIONS / "leaderboard.csv", index=False)
        champion = everything[0]
        joblib.dump(
            joblib.load(GENERATIONS / f"gen_{champion['generation']:02d}" / f"{champion['digest']}.joblib"),
            GENERATIONS / "champion.joblib", compress=3,
        )
        (GENERATIONS / "champion.json").write_text(json.dumps(champion, indent=2) + "\n")
        print(f"champion: {champion['digest']} from generation {champion['generation']}, "
              f"{champion['config']['family']}, mae {champion['metrics']['mae']:.5f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="evolve", choices=["evolve", "shard", "report"])
    parser.add_argument("--population", type=int, default=48)
    parser.add_argument("--generations", type=int, default=10)
    parser.add_argument("--shards", type=int, default=8)
    parser.add_argument("--elite", type=int, default=8)
    parser.add_argument("--plateau", type=float, default=0.15, help="percent gain that counts as progress")
    parser.add_argument("--patience", type=int, default=3, help="generations without gain before stopping")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--generation", type=int, default=0)
    parser.add_argument("--shard", type=int, default=0)
    arguments = parser.parse_args()

    if arguments.action == "shard":
        evaluate_shard(arguments.generation, arguments.shard, arguments.shards, arguments.device)
    elif arguments.action == "report":
        report()
    else:
        evolve(arguments.population, arguments.generations, arguments.shards,
               arguments.device, arguments.elite, arguments.plateau, arguments.patience)


if __name__ == "__main__":
    main()
