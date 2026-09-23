"""Wide model search on the local RTX 5090, written to artifacts/rtx5090-local/.

One candidate takes about two seconds, so a single process leaves the card idle.
This script draws a large randomised grid from the frozen search pack and runs
several shards at once on the same GPU:

    python -m scripts.train_rtx5090 --budget 240 --shards 6      # launches shards
    python -m scripts.train_rtx5090 run --shard 0 --shards 6     # one shard
    python -m scripts.train_rtx5090 summarise                    # table + ensemble

The search pack is the one prepared by scripts/search_models.py: training data
plus November/December 2025 validation. January 2026 targets are not in it and
must stay out — they are the untouched holdout.

Trained networks are exported as plain NumPy weights, so inference needs no GPU
and no torch. The card is used for the search only.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import platform
import random
import subprocess
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.data import ROOT
from src.model import FeatureRegressor, fit_mlp, metrics

SEARCH = ROOT / "artifacts/search"
DESTINATION = ROOT / "artifacts/rtx5090-local"
GRID_SEED = 20260923


def grid() -> list[dict]:
    """Full factorial grid; the run draws a reproducible sample from it."""
    rows = []
    for features, hidden, loss, rate, decay, batch, seed in itertools.product(
        ["point", "trajectory"],
        [(128, 64, 32), (256, 128, 64), (512, 256, 128), (512, 512, 256, 128), (1024, 512, 256)],
        ["mse", "mae", "huber"],
        [0.0003, 0.0007, 0.002],
        [0.005, 0.02],
        [1024, 4096],
        [101, 202, 303],
    ):
        rows.append(
            {
                "family": "mlp",
                "features": features,
                "hidden": list(hidden),
                "loss_name": loss,
                "learning_rate": rate,
                "weight_decay": decay,
                "batch_size": batch,
                "seed": seed,
                "epochs": 400,
                "patience": 40,
            }
        )
    return rows


def sample(budget: int) -> list[dict]:
    candidates = grid()
    random.Random(GRID_SEED).shuffle(candidates)
    return candidates[:budget]


def load_pack() -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    protocol_path = SEARCH / "protocol.json"
    if not protocol_path.exists():
        raise SystemExit(
            "Search pack missing. Build it first:\n"
            "    python scripts/search_models.py prepare"
        )
    protocol = json.loads(protocol_path.read_text())
    frames = []
    for name in ("train", "validation"):
        path = SEARCH / f"{name}.parquet"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != protocol[name + "_sha256"]:
            raise SystemExit(f"{path.name} does not match protocol.json; rebuild the search pack")
        frames.append(pd.read_parquet(path))
    if protocol.get("january_in_search_pack", False):
        raise SystemExit("Search pack contains January targets; refusing to train on the holdout")
    return protocol, frames[0], frames[1]


def run_shard(shard: int, shards: int, budget: int, device: str) -> None:
    protocol, train, valid = load_pack()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    configs = sample(budget)
    mine = [(i, c) for i, c in enumerate(configs) if i % shards == shard]
    print(f"shard {shard}/{shards}: {len(mine)} candidates on {device}", flush=True)

    for index, config in mine:
        name = f"rtx5090_{index:04d}"
        report = DESTINATION / f"{name}.json"
        if report.exists():
            continue
        columns = protocol["point_features"] if config["features"] == "point" else protocol["features"]
        x_train = train[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
        x_valid = valid[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
        started = time.monotonic()
        parameters = {k: v for k, v in config.items() if k not in {"family", "features"}}
        try:
            model, details = fit_mlp(
                x_train, train.power, x_valid, valid.power, device=device, **parameters
            )
        except RuntimeError as error:  # out of memory or CUDA failure
            report.write_text(json.dumps({"name": name, "config": config, "error": str(error)[:400]}) + "\n")
            print(f"{name}: failed — {str(error)[:120]}", flush=True)
            continue
        model = FeatureRegressor(model, columns)
        prediction = model.predict(x_valid)
        score = metrics(valid.power, prediction)
        monthly = {
            month: metrics(
                valid.loc[valid.hour.dt.strftime("%Y-%m") == month, "power"],
                prediction[(valid.hour.dt.strftime("%Y-%m") == month).to_numpy()],
            )
            for month in protocol["selection_months"]
        }
        info = {
            "name": name,
            "worker": "rtx5090-local",
            "hostname": platform.node(),
            "config": config,
            "metrics": score,
            "by_month": monthly,
            "fit": details,
            "seconds": round(time.monotonic() - started, 2),
            "train_sha256": protocol["train_sha256"],
            "validation_sha256": protocol["validation_sha256"],
        }
        joblib.dump({"model": model, "info": info}, DESTINATION / f"{name}.joblib", compress=3)
        np.save(DESTINATION / f"{name}.predictions.npy", prediction)
        report.write_text(json.dumps(info, indent=2) + "\n")
        print(f"{name}: mae {score['mae']:.5f}  {info['seconds']:5.1f}s  {config['features']}"
              f" {config['hidden']} {config['loss_name']}", flush=True)


def launch(budget: int, shards: int, device: str) -> None:
    """Start the shards side by side so the card is actually busy."""
    DESTINATION.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    processes = [
        subprocess.Popen(
            # Run as a module: the package layout is only importable that way.
            [sys.executable, "-m", "scripts.train_rtx5090", "run",
             "--shard", str(shard), "--shards", str(shards),
             "--budget", str(budget), "--device", device],
            cwd=ROOT,
            stdout=(DESTINATION / f"shard_{shard}.log").open("w"),
            stderr=subprocess.STDOUT,
        )
        for shard in range(shards)
    ]
    print(f"{shards} shards started, {budget} candidates total. Logs: {DESTINATION}/shard_*.log", flush=True)
    peak_memory, peak_load = 0, 0
    while any(process.poll() is None for process in processes):
        time.sleep(5)
        try:
            output = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip().splitlines()[0]
            memory, load = (int(value) for value in output.split(","))
            peak_memory, peak_load = max(peak_memory, memory), max(peak_load, load)
        except Exception:  # monitoring must never break the search
            pass
    failed = [shard for shard, process in enumerate(processes) if process.returncode]
    elapsed = time.monotonic() - started
    (DESTINATION / "run.json").write_text(
        json.dumps(
            {
                "device": device,
                "gpu": gpu_name(),
                "shards": shards,
                "budget": budget,
                "grid_seed": GRID_SEED,
                "grid_size": len(grid()),
                "seconds": round(elapsed, 1),
                "peak_gpu_memory_mib": peak_memory,
                "peak_gpu_utilisation_percent": peak_load,
                "failed_shards": failed,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"finished in {elapsed:.0f}s, peak GPU {peak_load}% and {peak_memory} MiB", flush=True)
    if failed:
        raise SystemExit(f"Shards failed: {failed}. See {DESTINATION}/shard_*.log")


def gpu_name() -> str | None:
    try:
        return subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or None
    except Exception:
        return None


def summarise(top: int) -> None:
    reports = sorted(DESTINATION.glob("rtx5090_*.json"))
    if not reports:
        raise SystemExit(f"No results in {DESTINATION}. Run the search first.")
    rows = [json.loads(path.read_text()) for path in reports]
    done = [row for row in rows if "metrics" in row]
    if not done:
        raise SystemExit("Every candidate failed; see the shard logs")
    done.sort(key=lambda row: row["metrics"]["mae"])
    print(f"{len(done)} candidates, {len(rows) - len(done)} failed\n")
    print(f"{'candidate':<16}{'mae':>9}{'rmse':>9}{'sec':>7}  features    hidden")
    for row in done[:top]:
        config = row["config"]
        print(f"{row['name']:<16}{row['metrics']['mae']:>9.5f}{row['metrics']['rmse']:>9.5f}"
              f"{row['seconds']:>7.1f}  {config['features']:<11} {config['hidden']}")

    # Averaging the best networks is usually better than any single one.
    _, _, valid = load_pack()
    best = done[:top]
    stacked = np.mean([np.load(DESTINATION / f"{row['name']}.predictions.npy") for row in best], axis=0)
    ensemble = metrics(valid.power, stacked)
    print(f"\nensemble of top {len(best)}: mae {ensemble['mae']:.5f}  rmse {ensemble['rmse']:.5f}")
    improvement = (done[0]["metrics"]["mae"] - ensemble["mae"]) / done[0]["metrics"]["mae"] * 100
    print(f"against the single best: {improvement:+.1f}%")

    # Three small files carry the result; the per-candidate artefacts stay local
    # because the search reproduces from GRID_SEED.
    pd.DataFrame(
        [
            {
                "name": row["name"],
                "mae": row["metrics"]["mae"],
                "rmse": row["metrics"]["rmse"],
                "seconds": row["seconds"],
                "features": row["config"]["features"],
                "hidden": "-".join(str(size) for size in row["config"]["hidden"]),
                "loss": row["config"]["loss_name"],
                "learning_rate": row["config"]["learning_rate"],
                "weight_decay": row["config"]["weight_decay"],
                "batch_size": row["config"]["batch_size"],
                "seed": row["config"]["seed"],
                "best_epoch": row["fit"].get("best_epoch"),
            }
            for row in done
        ]
    ).to_csv(DESTINATION / "leaderboard.csv", index=False)
    joblib.dump(
        joblib.load(DESTINATION / f"{done[0]['name']}.joblib"), DESTINATION / "best.joblib", compress=3
    )
    (DESTINATION / "summary.json").write_text(
        json.dumps(
            {
                "candidates": len(done),
                "failed": len(rows) - len(done),
                "best": {"name": done[0]["name"], "config": done[0]["config"], "metrics": done[0]["metrics"]},
                "ensemble": {"members": [row["name"] for row in best], "metrics": ensemble},
                "selection_months": ["2025-11", "2025-12"],
                "note": "Validation is November-December 2025. January 2026 is the untouched holdout.",
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nWritten: {DESTINATION / 'summary.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="launch", choices=["launch", "run", "summarise"])
    parser.add_argument("--budget", type=int, default=240, help="candidates drawn from the grid")
    parser.add_argument("--shards", type=int, default=6, help="processes sharing the GPU")
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--top", type=int, default=10)
    arguments = parser.parse_args()

    if arguments.action == "run":
        run_shard(arguments.shard, arguments.shards, arguments.budget, arguments.device)
    elif arguments.action == "summarise":
        summarise(arguments.top)
    else:
        launch(arguments.budget, arguments.shards, arguments.device)


if __name__ == "__main__":
    main()
