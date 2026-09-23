"""Evaluate the frozen shortlist on Nov/Dec 2024 using only earlier training."""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from scripts.search_models import SEARCH
from scripts.train_forecast import period
from src.model import fit_mlp, metrics


def main() -> None:
    protocol = json.loads((SEARCH / "protocol.json").read_text())
    shortlist = json.loads((SEARCH / "winter-shortlist.json").read_text())
    packed = pd.read_parquet(SEARCH / "train.parquet")
    training = packed.loc[packed.hour.lt("2024-10-31")]
    valid = pd.concat([period(packed, month, protocol["utc_offset_hours"], 23)
                       for month in ["2024-11", "2024-12"]], ignore_index=True)
    destination = SEARCH / "winter-2024"
    destination.mkdir(exist_ok=True)
    with threadpool_limits(limits=2):
        for row in shortlist:
            output = destination / (row["name"] + ".json")
            if output.exists():
                continue
            config = row["config"]
            columns = protocol["point_features"] if config["features"] == "point" else protocol["features"]
            x = training[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
            v = valid[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
            parameters = {k: val for k, val in config.items() if k not in {"family", "features"}}
            started = time.monotonic()
            if config["family"] == "mlp":
                parameters.update(epochs=row["fit"]["best_epoch"], cpu_threads=2)
                model, fit = fit_mlp(x, training.power, device="cuda", **parameters)
            else:
                model = HistGradientBoostingRegressor(early_stopping=False, random_state=42,
                                                     **parameters).fit(x, training.power)
                fit = {"device": "cpu"}
            prediction = model.predict(v)
            report = {"name": row["name"], "metrics": metrics(valid.power, prediction),
                      "by_month": {month: metrics(valid.loc[valid.hour.dt.strftime("%Y-%m").eq(month), "power"],
                                                   prediction[valid.hour.dt.strftime("%Y-%m").eq(month).to_numpy()])
                                   for month in ["2024-11", "2024-12"]},
                      "training_before": "2024-10-31", "training_rows": len(training), "fit": fit,
                      "seconds": round(time.monotonic() - started, 2),
                      "note": "Historical robustness check of candidates shortlisted on Nov/Dec 2025; not an independent test."}
            output.write_text(json.dumps(report, indent=2) + "\n")
            np.save(destination / (row["name"] + ".predictions.npy"), prediction)
            print(json.dumps({"name": row["name"], "mae": report["metrics"]["mae"]}), flush=True)
    valid[["as_of", "valid_time", "hour", "turbine_id", "power"]].to_parquet(destination / "targets.parquet", index=False)


if __name__ == "__main__":
    main()
