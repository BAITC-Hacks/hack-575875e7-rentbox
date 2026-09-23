"""Train power forecasting on operational GFS with observed publication times."""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import os
import platform
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from scripts.search_models import cpu_configs
from scripts.train_forecast import period, score_groups
from src.data import ROOT, load_hourly
from src.gfs_model import features, predict
from src.gfs_weather import CACHE, load_runs
from src.model import BlendRegressor, FeatureRegressor, fit_mlp, metrics

SEARCH = ROOT / "artifacts/gfs-search"
OUTPUT = ROOT / "artifacts/gfs-model"


def packed_data():
    weather, manifests = load_runs()
    actuals, provenance = load_hourly(timestamp_convention="start")
    actuals["valid_time"] = (actuals.hour - pd.Timedelta(hours=5)).dt.tz_localize("UTC")
    # Compute full available trajectories BEFORE joining or dropping missing targets.
    values = features(weather, trajectory=True)
    packed = pd.concat([weather[["as_of", "valid_time", "turbine_id", "lead_hour", "initialization_time", "available_at"]], values.add_prefix("x_")], axis=1)
    packed = packed.merge(actuals[["hour", "valid_time", "turbine_id", "power"]],
                          on=["valid_time", "turbine_id"], how="inner", validate="many_to_one")
    return packed, weather, manifests, provenance


def prepare() -> None:
    expected = {str(day.date()) for day in pd.date_range("2024-03-01", "2026-02-28")}
    found = {path.stem for path in CACHE.glob("????-??-??.csv")}
    missing = sorted(expected - found)
    if missing:
        raise ValueError(f"GFS archive is incomplete: {len(missing)} days missing, first {missing[:5]}")
    packed, weather, manifests, provenance = packed_data()
    train = packed.loc[packed.hour.lt("2025-10-31")].copy()
    valid = pd.concat([period(packed, month, 5, 23) for month in ["2025-11", "2025-12"]], ignore_index=True)
    SEARCH.mkdir(parents=True, exist_ok=True)
    train.to_parquet(SEARCH / "train.parquet", index=False)
    valid.to_parquet(SEARCH / "validation.parquet", index=False)
    protocol = {"kind": "noaa_gfs_operational_forecast", "train_before": "2025-10-31",
        "utc_offset_hours": 5, "timestamp_convention": "start", "issue_hour": 23,
        "time_settings_confirmed": False, "selection_months": ["2025-11", "2025-12"],
        "january_in_search_pack": False, "point_features": list(features(weather).columns),
        "features": list(features(weather, True).columns), "data": provenance,
        "train_rows": len(train), "validation_rows": len(valid),
        "weather": {"days": len(manifests), "availability": "Original S3 Last-Modified <= as_of, verified for every source object",
                    "manifest_sha256": hashlib.sha256(json.dumps(manifests, sort_keys=True).encode()).hexdigest()},
        **{key + "_sha256": hashlib.sha256((SEARCH / (key + ".parquet")).read_bytes()).hexdigest()
           for key in ["train", "validation"]}}
    (SEARCH / "protocol.json").write_text(json.dumps(protocol, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: protocol[k] for k in ["train_rows", "validation_rows", "weather"]}), flush=True)


def configurations(worker: str) -> list[dict]:
    if worker == "cpu":
        return cpu_configs()
    seeds = [211, 307] if worker == "local-gpu" else [401, 503]
    result = []
    for feature_set, hidden, loss, rate, seed in itertools.product(
        ["point", "trajectory"], [(64, 32), (128, 64, 32), (256, 128, 64), (512, 256, 128), (512, 512, 256, 128)],
        ["mae", "huber", "mse"], [0.0003, 0.0007, 0.002], seeds,
    ):
        result.append({"family": "mlp", "features": feature_set, "hidden": list(hidden),
                       "loss_name": loss, "learning_rate": rate, "seed": seed, "epochs": 350,
                       "patience": 40, "batch_size": 2048, "weight_decay": 0.02, "cpu_threads": 2})
    random.Random(20260923).shuffle(result)
    return result


def fit_config(config: dict, train: pd.DataFrame, protocol: dict, valid: pd.DataFrame | None = None,
               epochs: int | None = None):
    columns = protocol["point_features"] if config["features"] == "point" else protocol["features"]
    x = train[["x_" + c for c in columns]].rename(columns=lambda c:c[2:])
    params = {k: v for k, v in config.items() if k not in {"family", "features"}}
    if config["family"] == "mlp":
        if epochs is not None:
            params["epochs"] = epochs
        v = None if valid is None else valid[["x_" + c for c in columns]].rename(columns=lambda c:c[2:])
        model, details = fit_mlp(x, train.power, v, None if valid is None else valid.power, device="cuda", **params)
    else:
        if config["family"] == "boost":
            model = HistGradientBoostingRegressor(early_stopping=False, random_state=42, **params)
        else:
            model = ExtraTreesRegressor(max_features=0.8, n_jobs=2, random_state=42, **params)
        model.fit(x, train.power)
        details = {"device": "cpu"}
    return FeatureRegressor(model, columns), details


def train_worker(worker: str, shard: int, shards: int) -> None:
    protocol = json.loads((SEARCH / "protocol.json").read_text())
    for split in ["train", "validation"]:
        if hashlib.sha256((SEARCH / (split + ".parquet")).read_bytes()).hexdigest() != protocol[split + "_sha256"]:
            raise ValueError("Training pack changed")
    train, valid = [pd.read_parquet(SEARCH / (s + ".parquet")) for s in ["train", "validation"]]
    if not train.hour.lt(protocol["train_before"]).all():
        raise ValueError("Search training crossed its historical cutoff")
    if not valid.hour.dt.strftime("%Y-%m").isin(protocol["selection_months"]).all():
        raise ValueError("Search validation includes an undeclared month")
    output = SEARCH / worker
    output.mkdir(parents=True, exist_ok=True)
    with threadpool_limits(limits=2):
        for index, config in enumerate(configurations(worker)):
            if index % shards != shard:
                continue
            name = f"{worker}_{index:03d}"
            report = output / (name + ".json")
            if (report.exists() and (output / (name + ".joblib")).exists()
                    and (output / (name + ".predictions.npy")).exists()):
                previous = json.loads(report.read_text())
                if (previous.get("config") != config
                        or any(previous.get(k) != protocol[k]
                               for k in ["train_sha256", "validation_sha256"])):
                    raise ValueError(f"Candidate {name} belongs to another search; use a new output directory")
                continue
            started = time.monotonic()
            model, fit = fit_config(config, train, protocol, valid)
            v = valid[["x_" + c for c in model.columns]].rename(columns=lambda c:c[2:])
            prediction = model.predict(v)
            info = {"name": name, "config": config, "fit": fit, "hostname": platform.node(),
                    "metrics": metrics(valid.power, prediction), "seconds": round(time.monotonic()-started,2),
                    "by_month": {month: metrics(valid.loc[valid.hour.dt.strftime("%Y-%m").eq(month), "power"],
                                                  prediction[valid.hour.dt.strftime("%Y-%m").eq(month).to_numpy()])
                                 for month in protocol["selection_months"]},
                    "train_sha256": protocol["train_sha256"], "validation_sha256": protocol["validation_sha256"]}
            joblib.dump({"model": model, "info": info}, output / (name + ".joblib"), compress=3)
            np.save(output / (name + ".predictions.npy"), prediction)
            report.write_text(json.dumps(info, indent=2) + "\n")
            print(json.dumps({"name": name, "mae": info["metrics"]["mae"], "seconds": info["seconds"]}), flush=True)


def finalize(workers: list[str] | None = None) -> None:
    workers = list(dict.fromkeys(workers or ["cpu", "local-gpu", "cloud-gpu"]))
    protocol = json.loads((SEARCH / "protocol.json").read_text())
    if hashlib.sha256((SEARCH / "validation.parquet").read_bytes()).hexdigest() != protocol["validation_sha256"]:
        raise ValueError("Validation pack changed")
    valid = pd.read_parquet(SEARCH / "validation.parquet")
    candidates = []
    for worker in workers:
        expected = len(configurations(worker))
        reports = [SEARCH / worker / f"{worker}_{index:03d}.json" for index in range(expected)]
        complete = [path for path in reports if path.exists()
                    and path.with_suffix(".joblib").exists()
                    and path.with_suffix(".predictions.npy").exists()]
        if len(complete) != expected:
            raise ValueError(f"Search incomplete: {worker} {len(complete)}/{expected}")
        candidates.extend(complete)
    rows = []
    for path in sorted(candidates):
        info = json.loads(path.read_text())
        if "config" not in info:
            continue
        if any(info[k] != protocol[k] for k in ["train_sha256", "validation_sha256"]):
            raise ValueError("Candidate data mismatch")
        prediction_path = path.with_suffix(".predictions.npy").resolve()
        info["prediction_path"] = str(prediction_path.relative_to(ROOT) if prediction_path.is_relative_to(ROOT) else prediction_path)
        rows.append(info)
    if not rows:
        raise ValueError("No completed GFS candidates")
    rows.sort(key=lambda r:r["metrics"]["mae"])
    ensembles = []
    for count in [1, 3, 5, 8, 12, 20]:
        if count > len(rows):
            continue
        prediction = np.mean([np.load(ROOT / r["prediction_path"]) for r in rows[:count]], axis=0)
        ensembles.append({"count": count, "members": [r["name"] for r in rows[:count]], "metrics": metrics(valid.power, prediction)})
    chosen = min(ensembles, key=lambda e:e["metrics"]["mae"])
    members = rows[:chosen["count"]]
    selection = {"candidate_count": len(rows), "workers": workers, "ranking": rows, "ensembles": ensembles,
                 "chosen": chosen, "selection_months": protocol["selection_months"], "january_used_for_search": False}
    (SEARCH / "selection.json").write_text(json.dumps(selection, indent=2) + "\n")
    print(json.dumps({"selection_frozen": chosen}), flush=True)
    packed, weather, _manifests, provenance = packed_data()
    january = period(packed, "2026-01", 5, 23)
    before_january = packed.loc[packed.hour.lt("2025-12-31")]
    before_february = packed.loc[packed.hour.lt("2026-01-31")]
    contextual = any(m["config"]["features"] == "trajectory" for m in members)
    columns = protocol["features"] if contextual else protocol["point_features"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with threadpool_limits(limits=2):
        def fit_all(training):
            return BlendRegressor([fit_config(m["config"], training, protocol, epochs=m["fit"].get("best_epoch"))[0] for m in members])
        validation_model = fit_all(before_january)
        prediction = validation_model.predict(january[["x_" + c for c in columns]].rename(columns=lambda c:c[2:]))
        final_model = fit_all(before_february)
    january_score = score_groups(january, prediction)
    january_output = january[["as_of", "valid_time", "turbine_id", "lead_hour", "initialization_time", "available_at", "power"]].copy()
    january_output["predicted_power"] = prediction
    january_output.to_csv(OUTPUT / "january_predictions.csv", index=False)
    metadata = {"kind": "noaa_gfs_operational_forecast", "winner": f"gfs_top_{chosen['count']}_mean",
        "feature_set": "trajectory" if contextual else "point", "features": columns, "members": members,
        "created_at": datetime.now(timezone.utc).isoformat(), "data": provenance,
        "training_rows": len(before_february), "training_data_available_until": (before_february.valid_time.max() + pd.Timedelta(hours=1)).isoformat(),
        "time_assumptions": {"utc_offset_hours": 5, "timestamp_convention": "start", "daily_issue_hour": 23, "confirmed_by_organizers": False},
        "search": {"candidate_count": len(rows), "workers": workers, "selection_months": protocol["selection_months"], "chosen": chosen, "january_used_for_search": False},
        "january": january_score, "weather": protocol["weather"],
        "note": "January is a development monitoring month; February actuals are absent. Availability checked against original GFS S3 object timestamps."}
    validation_metadata = copy.deepcopy(metadata)
    validation_metadata.update(training_rows=len(before_january), training_data_available_until=(before_january.valid_time.max()+pd.Timedelta(hours=1)).isoformat())
    joblib.dump({"model": validation_model, "metadata": validation_metadata}, OUTPUT / "validation_model.joblib", compress=3)
    bundle = {"model": final_model, "metadata": metadata}
    joblib.dump(bundle, OUTPUT / "model.joblib", compress=3)
    metadata["artifact_sha256"] = hashlib.sha256((OUTPUT / "model.joblib").read_bytes()).hexdigest()
    (OUTPUT / "metrics.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    replay = weather.loc[weather.as_of.ge("2026-01-31T18:00:00Z") & weather.as_of.le("2026-02-28T18:00:00Z")].copy()
    with threadpool_limits(limits=2):
        replay["predicted_power"] = predict(bundle, replay)
    replay["target_source_clock"] = (replay.valid_time + pd.Timedelta(hours=5)).dt.tz_localize(None)
    replay["in_february"] = replay.target_source_clock.ge("2026-02-01") & replay.target_source_clock.lt("2026-03-01")
    replay[["as_of", "valid_time", "target_source_clock", "turbine_id", "lead_hour", "predicted_power", "initialization_time", "available_at", "in_february"]].to_csv(OUTPUT / "february_replay.csv", index=False)
    print(json.dumps({"january": january_score, "artifact": str(OUTPUT / "model.joblib"), "february_rows": len(replay)}), flush=True)


def main() -> None:
    global SEARCH, OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "train", "finalize"])
    parser.add_argument("--worker", choices=["cpu", "local-gpu", "cloud-gpu"], default="local-gpu")
    parser.add_argument("--workers", nargs="+", choices=["cpu", "local-gpu", "cloud-gpu"],
                        help="Completed workers included in finalize; defaults to all three")
    parser.add_argument("--search-dir", type=Path, default=SEARCH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--shard", type=int)
    args = parser.parse_args()
    SEARCH, OUTPUT = args.search_dir.resolve(), args.output_dir.resolve()
    if args.shards < 1 or (args.shard is not None and not 0 <= args.shard < args.shards):
        parser.error("shards must be positive and shard must be in [0, shards)")
    if args.action == "prepare":
        prepare()
    elif args.action == "finalize":
        finalize(args.workers)
    elif args.shard is not None:
        train_worker(args.worker, args.shard, args.shards)
    else:
        output = SEARCH / args.worker
        output.mkdir(parents=True, exist_ok=True)
        jobs = []
        for shard in range(args.shards):
            with (output / f"shard-{shard}.log").open("w") as logfile:
                jobs.append(subprocess.Popen([sys.executable, "-m", "scripts.train_gfs", "train", "--worker", args.worker,
                    "--shards", str(args.shards), "--shard", str(shard), "--search-dir", str(SEARCH)], cwd=ROOT,
                    env={**os.environ, "OPENBLAS_NUM_THREADS": "2", "OMP_NUM_THREADS": "2"}, stdout=logfile, stderr=subprocess.STDOUT))
        codes = [job.wait() for job in jobs]
        print(json.dumps({"worker": args.worker, "exit_codes": codes}), flush=True)
        if any(codes):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
