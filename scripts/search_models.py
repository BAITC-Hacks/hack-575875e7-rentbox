"""Distribute a frozen model search across local CPU, local GPU and Brev GPU.

The search pack contains training data and November/December validation only.
January targets are never sent to search workers. Every candidate is saved.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import platform
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from scripts.train_forecast import daily_schedule, period
from src.data import ROOT, load_hourly
from src.model import (
    FeatureRegressor,
    context_weather_features,
    fit_mlp,
    metrics,
    weather_features,
)
from src.weather import load_archive

SEARCH = ROOT / "artifacts/search"


def prepare(offset: int, convention: str) -> None:
    SEARCH.mkdir(parents=True, exist_ok=True)
    hourly, provenance = load_hourly(timestamp_convention=convention)
    archive, manifests = load_archive()
    hourly["valid_time"] = (hourly.hour - pd.Timedelta(hours=offset)).dt.tz_localize("UTC")
    scheduled = daily_schedule(archive, offset, 23)
    grouped = scheduled.groupby(["as_of", "turbine_id"]).valid_time.transform("size")
    scheduled = scheduled.loc[grouped == 48].copy()
    features = context_weather_features(scheduled)
    finite = np.isfinite(features.to_numpy()).all(axis=1)
    scheduled = scheduled.loc[finite].copy()
    features = features.loc[finite].copy()
    # Feature names overlap keys. Store features under x_ names to make the join explicit.
    packed = pd.concat([scheduled[["as_of", "valid_time", "turbine_id", "lead_hour"]], features.add_prefix("x_")], axis=1)
    packed = packed.merge(hourly[["hour", "valid_time", "turbine_id", "power"]],
                          on=["valid_time", "turbine_id"], validate="many_to_one", how="inner")
    packed = packed.loc[packed.hour >= "2024-03-02"].copy()
    train = packed.loc[packed.hour < "2025-10-31"].copy()
    validation = pd.concat([period(packed, month, offset, 23) for month in ["2025-11", "2025-12"]], ignore_index=True)
    train.to_parquet(SEARCH / "train.parquet", index=False)
    validation.to_parquet(SEARCH / "validation.parquet", index=False)
    meta = {
        "utc_offset_hours": offset, "timestamp_convention": convention, "issue_hour": 23,
        "time_settings_confirmed": False, "train_before": "2025-10-31",
        "selection_months": ["2025-11", "2025-12"], "january_in_search_pack": False,
        "features": list(features.columns), "point_features": list(weather_features(scheduled).columns),
        "data": provenance, "weather_manifest": manifests,
        "train_rows": len(train), "validation_rows": len(validation),
    }
    for name in ["train", "validation"]:
        meta[name + "_sha256"] = hashlib.sha256((SEARCH / f"{name}.parquet").read_bytes()).hexdigest()
    (SEARCH / "protocol.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: meta[k] for k in ["train_rows", "validation_rows", "january_in_search_pack"]}), flush=True)


def cpu_configs() -> list[dict]:
    rows = []
    for features, loss, leaves, count, regularization in itertools.product(
        ["point", "trajectory"], ["absolute_error", "squared_error"], [7, 15, 31, 63], [250, 500], [10]
    ):
        rows.append({"family": "boost", "features": features, "loss": loss, "max_leaf_nodes": leaves,
                     "max_iter": count, "l2_regularization": regularization, "min_samples_leaf": 60,
                     "learning_rate": 0.05})
    for features, depth, leaf in itertools.product(["point", "trajectory"], [12, 20], [8, 30]):
        rows.append({"family": "extra_trees", "features": features, "max_depth": depth,
                     "min_samples_leaf": leaf, "n_estimators": 300})
    return rows


def gpu_configs(worker: str) -> list[dict]:
    # Fixed disjoint seed sets for local and cloud; no adaptive January feedback.
    seeds = [11, 29] if worker == "local-gpu" else [53, 83]
    rows = []
    for features, hidden, loss, seed in itertools.product(
        ["point", "trajectory"], [(128, 64, 32), (256, 128, 64)], ["mse", "huber", "mae"], seeds
    ):
        rows.append({"family": "mlp", "features": features, "hidden": list(hidden), "loss_name": loss,
                     "seed": seed, "epochs": 250, "learning_rate": 0.0007,
                     "weight_decay": 0.02, "batch_size": 2048, "patience": 35})
    return rows


def train_worker(worker: str, device: str, limit: int | None) -> None:
    protocol = json.loads((SEARCH / "protocol.json").read_text())
    for name in ["train", "validation"]:
        if hashlib.sha256((SEARCH / f"{name}.parquet").read_bytes()).hexdigest() != protocol[name + "_sha256"]:
            raise ValueError("Search pack checksum mismatch")
    train, valid = [pd.read_parquet(SEARCH / f"{name}.parquet") for name in ["train", "validation"]]
    destination = SEARCH / worker
    destination.mkdir(parents=True, exist_ok=True)
    configs = cpu_configs() if worker == "local-cpu" else gpu_configs(worker)
    if limit is not None:
        configs = configs[:limit]
    with threadpool_limits(limits=8):
        for index, config in enumerate(configs):
            name = f"{worker}_{index:03d}"
            report_path = destination / f"{name}.json"
            if report_path.exists() and (destination / f"{name}.joblib").exists():
                print(f"Cached {name}", flush=True)
                continue
            columns = protocol["point_features"] if config["features"] == "point" else protocol["features"]
            x_train = train[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
            x_valid = valid[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
            started = time.monotonic()
            parameters = {k: v for k, v in config.items() if k not in {"family", "features"}}
            details = {}
            if config["family"] == "mlp":
                model, details = fit_mlp(x_train, train.power, x_valid, valid.power,
                                         device=device, **parameters)
            else:
                if config["family"] == "boost":
                    model = HistGradientBoostingRegressor(early_stopping=False, random_state=42, **parameters)
                else:
                    model = ExtraTreesRegressor(max_features=0.8, n_jobs=8, random_state=42, **parameters)
                model.fit(x_train, train.power)
            model = FeatureRegressor(model, columns)
            prediction = model.predict(x_valid)
            score = metrics(valid.power, prediction)
            monthly = {}
            for month in protocol["selection_months"]:
                mask = valid.hour.dt.strftime("%Y-%m") == month
                monthly[month] = metrics(valid.loc[mask, "power"], prediction[mask.to_numpy()])
            info = {"name": name, "worker": worker, "hostname": platform.node(), "config": config,
                    "metrics": score, "by_month": monthly, "fit": details,
                    "seconds": round(time.monotonic() - started, 2),
                    "train_sha256": protocol["train_sha256"], "validation_sha256": protocol["validation_sha256"]}
            joblib.dump({"model": model, "info": info}, destination / f"{name}.joblib", compress=3)
            np.save(destination / f"{name}.predictions.npy", prediction)
            report_path.write_text(json.dumps(info, indent=2) + "\n")
            print(json.dumps({"candidate": name, "mae": score["mae"], "rmse": score["rmse"],
                              "seconds": info["seconds"], "config": config}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "train"])
    parser.add_argument("--utc-offset", type=int, default=5)
    parser.add_argument("--timestamp-convention", choices=["start", "end"], default="start")
    parser.add_argument("--worker", choices=["local-cpu", "local-gpu", "cloud-gpu"], default="local-gpu")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.utc_offset, args.timestamp_convention)
    else:
        train_worker(args.worker, args.device, args.limit)


if __name__ == "__main__":
    main()
