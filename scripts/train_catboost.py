"""GPU boosting on the frozen Nov/Dec search pack; CatBoost is training-only."""

from __future__ import annotations

import hashlib
import itertools
import json
import platform
import time

import numpy as np
import pandas as pd

from scripts.search_models import SEARCH
from src.data import ROOT
from src.model import metrics


def main() -> None:
    import catboost

    protocol = json.loads((SEARCH / "protocol.json").read_text())
    for split in ("train", "validation"):
        if hashlib.sha256((SEARCH / f"{split}.parquet").read_bytes()).hexdigest() != protocol[f"{split}_sha256"]:
            raise ValueError("Search data changed")
    train, valid = [pd.read_parquet(SEARCH / f"{split}.parquet") for split in ("train", "validation")]
    output = ROOT / "artifacts/catboost-search"
    output.mkdir(parents=True, exist_ok=True)
    grid = list(itertools.product(["point", "trajectory"], [4, 6, 8], ["MAE", "Huber:delta=0.1", "RMSE"], [0.025, 0.08]))
    for index, (features, depth, loss, rate) in enumerate(grid):
        name = f"catboost_{index:03d}"
        path = output / f"{name}.json"
        if path.exists() and (output / f"{name}.predictions.npy").exists():
            continue
        columns = protocol["point_features"] if features == "point" else protocol["features"]
        x = train[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
        v = valid[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
        config = {"family": "catboost", "features": features, "depth": depth,
                  "loss_function": loss, "learning_rate": rate, "l2_leaf_reg": 8,
                  "random_seed": 197, "iterations": 2400}
        params = {k: val for k, val in config.items() if k not in {"family", "features"}}
        started = time.monotonic()
        model = catboost.CatBoostRegressor(
            **params, eval_metric="MAE", task_type="GPU", devices="0", gpu_ram_part=0.65,
            thread_count=4, allow_writing_files=False, verbose=False,
        )
        model.fit(x, train.power, eval_set=(v, valid.power), early_stopping_rounds=160)
        prediction = np.clip(model.predict(v), 0, 1)
        report = {
            "name": name, "worker": "catboost-search", "hostname": platform.node(),
            "config": config, "features": columns, "metrics": metrics(valid.power, prediction),
            "fit": {"best_iteration": model.get_best_iteration(), "tree_count": model.tree_count_,
                    "device": "GPU", "gpu": "NVIDIA RTX A6000", "catboost": catboost.__version__,
                    "note": "GPU floating point reductions are not bitwise deterministic."},
            "by_month": {month: metrics(valid.loc[valid.hour.dt.strftime("%Y-%m").eq(month), "power"],
                                         prediction[valid.hour.dt.strftime("%Y-%m").eq(month).to_numpy()])
                         for month in protocol["selection_months"]},
            "seconds": round(time.monotonic() - started, 2),
            "train_sha256": protocol["train_sha256"], "validation_sha256": protocol["validation_sha256"],
        }
        model.save_model(str(output / f"{name}.model.json"), format="json")
        np.save(output / f"{name}.predictions.npy", prediction)
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"candidate": name, "mae": report["metrics"]["mae"],
                          "seconds": report["seconds"], "trees": model.tree_count_}), flush=True)
    (output / "run.json").write_text(json.dumps({"candidate_count": len(grid),
        "hardware": "NVIDIA RTX A6000", "january_used_for_search": False}, indent=2) + "\n")


if __name__ == "__main__":
    main()
