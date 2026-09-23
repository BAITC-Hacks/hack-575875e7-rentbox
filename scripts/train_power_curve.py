"""Train a wind-to-power diagnostic; metrics assume OBSERVED future weather.

This is a component for a weather-driven forecast, not a 24/48-hour backtest.
Usage: python -m scripts.train_power_curve --device cuda
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn
from threadpoolctl import threadpool_limits

from src.data import ROOT, load_hourly
from src.model import cpu_candidates, fit_mlp, metrics, observed_features


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--timestamp-convention", choices=["start", "end"], default="start")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/power_curve")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    frame, provenance = load_hourly(timestamp_convention=args.timestamp_convention)
    train = frame.loc[frame.hour < "2025-12-01"]
    selection = frame.loc[(frame.hour >= "2025-12-01") & (frame.hour < "2026-01-01")]
    holdout = frame.loc[frame.hour >= "2026-01-01"]
    x_train, x_selection, x_holdout = [observed_features(f) for f in [train, selection, holdout]]
    candidates, rows = cpu_candidates(), []
    with threadpool_limits(limits=8):
        for name, model in candidates.items():
            start = time.monotonic()
            model.fit(x_train, train.power.to_numpy())
            row = {"model": name, "selection_december": metrics(selection.power, model.predict(x_selection)),
                   "seconds": round(time.monotonic() - start, 2)}
            rows.append(row)
            print(json.dumps(row), flush=True)
        neural, training = fit_mlp(x_train, train.power, x_selection, selection.power, device=args.device)
        candidates["neural_network"] = neural
        row = {"model": "neural_network", "selection_december": metrics(selection.power, neural.predict(x_selection)), **training}
        rows.append(row)
        print(json.dumps(row), flush=True)
        winner = min(rows, key=lambda row: row["selection_december"]["mae"])["model"]
        # Winner is frozen BEFORE examining any January targets.
        model = candidates[winner]
        pre_january = frame.loc[frame.hour < "2026-01-01"]
        if winner == "neural_network":
            model, _ = fit_mlp(observed_features(pre_january), pre_january.power,
                               device=args.device, epochs=training["best_epoch"])
        else:
            model.fit(observed_features(pre_january), pre_january.power)
        predictions = np.clip(model.predict(x_holdout), 0, 1)
        holdout_result = metrics(holdout.power, predictions)
        by_turbine = {str(t): metrics(holdout.loc[holdout.turbine_id == t, "power"],
                                     predictions[holdout.turbine_id.to_numpy() == t]) for t in [1, 2]}
        output = holdout[["hour", "turbine_id", "power", "wind_speed", "temperature"]].copy()
        output["predicted_power"] = predictions
        output.to_csv(args.output / "january_diagnostic.csv", index=False)
        # Leave Jan 31 entirely out so the artifact can be used on Jan 31.
        final = frame.loc[frame.hour < "2026-01-31"]
        if winner == "neural_network":
            model, _ = fit_mlp(observed_features(final), final.power,
                               device=args.device, epochs=training["best_epoch"])
        else:
            model.fit(observed_features(final), final.power)
        metadata = {
            "kind": "observed_weather_power_curve_diagnostic", "winner": winner,
            "warning": "January metrics use observed weather, NOT day-ahead forecast weather; do not present as forecast accuracy.",
            "created_at": datetime.now(timezone.utc).isoformat(), "data": provenance,
            "split": {"train_before": "2025-12-01", "model_selection": "2025-12",
                      "untouched_holdout": "2026-01", "final_refit_before": "2026-01-31"},
            "selection_metric": "MAE; December only", "candidates": rows,
            "january_diagnostic": holdout_result, "january_by_turbine": by_turbine,
            "features": list(x_train.columns),
            "versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__},
        }
        joblib.dump({"model": model, "metadata": metadata}, args.output / "model.joblib", compress=3)
        (args.output / "metrics.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps({"winner": winner, "january_observed_weather_diagnostic": holdout_result,
                          "artifact": str(args.output / "model.joblib")}), flush=True)


if __name__ == "__main__":
    main()
