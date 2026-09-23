"""Broad A6000 search with disjoint seeds, four workers and resumable outputs."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import platform
import random
import subprocess
import sys
import time

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from scripts.search_models import SEARCH
from src.data import ROOT
from src.model import FeatureRegressor, fit_mlp, metrics

DESTINATION = ROOT / "artifacts/a6000-wide"


def configurations(budget: int) -> list[dict]:
    rows = []
    for feature_set, layers, loss, rate, decay, batch, seed in itertools.product(
        ["point", "trajectory"],
        [(128, 64, 32), (256, 128, 64), (512, 256, 128), (512, 512, 256, 128), (1024, 512, 256)],
        ["mae", "huber", "mse"], [0.0003, 0.0007, 0.002], [0.005, 0.02], [1024, 4096], [401, 503, 607],
    ):
        rows.append({"family": "mlp", "features": feature_set, "hidden": list(layers),
                     "loss_name": loss, "learning_rate": rate, "weight_decay": decay,
                     "batch_size": batch, "seed": seed, "epochs": 400, "patience": 40, "cpu_threads": 2})
    random.Random(20260924).shuffle(rows)
    return rows[:budget]


def worker(shard: int, shards: int, budget: int) -> None:
    protocol = json.loads((SEARCH / "protocol.json").read_text())
    for name in ["train", "validation"]:
        if hashlib.sha256((SEARCH / f"{name}.parquet").read_bytes()).hexdigest() != protocol[name + "_sha256"]:
            raise ValueError("Search pack checksum mismatch")
    train, valid = [pd.read_parquet(SEARCH / f"{name}.parquet") for name in ["train", "validation"]]
    DESTINATION.mkdir(parents=True, exist_ok=True)
    with threadpool_limits(limits=2):
        for index, config in enumerate(configurations(budget)):
            if index % shards != shard:
                continue
            name = f"a6000_{index:04d}"
            report = DESTINATION / f"{name}.json"
            if report.exists() and (DESTINATION / f"{name}.joblib").exists():
                continue
            columns = protocol["point_features"] if config["features"] == "point" else protocol["features"]
            x = train[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
            v = valid[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
            started = time.monotonic()
            params = {k: val for k, val in config.items() if k not in {"family", "features"}}
            model, fit = fit_mlp(x, train.power, v, valid.power, device="cuda", **params)
            model = FeatureRegressor(model, columns)
            prediction = model.predict(v)
            info = {"name": name, "worker": "a6000-wide", "hostname": platform.node(), "config": config,
                    "metrics": metrics(valid.power, prediction), "fit": fit,
                    "by_month": {month: metrics(valid.loc[valid.hour.dt.strftime("%Y-%m").eq(month), "power"],
                                                 prediction[valid.hour.dt.strftime("%Y-%m").eq(month).to_numpy()])
                                 for month in protocol["selection_months"]},
                    "seconds": round(time.monotonic() - started, 2),
                    "train_sha256": protocol["train_sha256"], "validation_sha256": protocol["validation_sha256"]}
            joblib.dump({"model": model, "info": info}, DESTINATION / f"{name}.joblib", compress=3)
            np.save(DESTINATION / f"{name}.predictions.npy", prediction)
            report.write_text(json.dumps(info, indent=2) + "\n")
            print(json.dumps({"candidate": name, "mae": info["metrics"]["mae"], "seconds": info["seconds"]}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=480)
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--shard", type=int)
    args = parser.parse_args()
    if args.shard is not None:
        worker(args.shard, args.shards, args.budget)
        return
    DESTINATION.mkdir(parents=True, exist_ok=True)
    processes = []
    started = time.monotonic()
    for shard in range(args.shards):
        logfile = (DESTINATION / f"shard_{shard}.log").open("w")
        processes.append(subprocess.Popen(
            [sys.executable, "-m", "scripts.train_cloud_wide", "--budget", str(args.budget),
             "--shards", str(args.shards), "--shard", str(shard)], cwd=ROOT,
            stdout=logfile, stderr=subprocess.STDOUT,
            env={**os.environ, "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"},
        ))
        logfile.close()
    print(f"Started {args.shards} A6000 workers, {args.budget} candidates", flush=True)
    codes = [process.wait() for process in processes]
    (DESTINATION / "run.json").write_text(json.dumps({"budget": args.budget, "shards": args.shards,
        "seconds": round(time.monotonic()-started, 2), "exit_codes": codes, "hardware": "NVIDIA RTX A6000"}, indent=2) + "\n")
    if any(codes):
        raise SystemExit(f"Worker failures: {codes}")


if __name__ == "__main__":
    main()
