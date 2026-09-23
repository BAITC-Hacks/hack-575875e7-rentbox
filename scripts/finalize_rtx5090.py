"""Freeze the RTX 5090 search into one ensemble and report January once.

Mirrors scripts/finalize_search.py, but for the candidates produced locally by
train_rtx5090.py (flat search) and evolve_rtx5090.py (generational search).
That script is left untouched: it validates a fixed roster of three workers and
would reject these results.

Selection happens on November-December 2025. The chosen members are then refit on
everything available before January, and January is scored once — it is a holdout,
not a tuning signal.

    python -m scripts.finalize_rtx5090 --members 10
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from threadpoolctl import threadpool_limits

from scripts.finalize_search import fit_candidate
from scripts.train_forecast import daily_schedule, period, score_groups
from scripts.train_rtx5090 import DESTINATION, load_pack
from src.data import load_hourly
from src.model import BlendRegressor, context_weather_features, metrics
from src.weather import load_archive

OUTPUT = DESTINATION / "ensemble"
GENERATIONS = DESTINATION / "generations"


def candidates() -> list[dict]:
    """Every finished candidate from both local searches, best first."""
    rows = []
    for path in glob.glob(str(DESTINATION / "rtx5090_*.json")):
        row = json.loads(Path(path).read_text())
        if "metrics" in row:
            row["prediction_path"] = str(Path(path).with_suffix("")) + ".predictions.npy"
            row["origin"] = "flat"
            rows.append(row)
    for folder in sorted(GENERATIONS.glob("gen_*")):
        for path in folder.glob("*.json"):
            if path.name == "population.json":
                continue
            row = json.loads(path.read_text())
            if "metrics" in row:
                row["name"] = row["digest"]
                row["prediction_path"] = str(folder / f"{row['digest']}.predictions.npy")
                row["origin"] = f"generation {row['generation']}"
                rows.append(row)
    rows.sort(key=lambda row: row["metrics"]["mae"])
    return rows


def refit(info: dict, training: pd.DataFrame, protocol: dict):
    """Refit one member, dropping genes the shared fitter does not accept.

    The generational search carries a ``bias_correction`` gene that is applied
    outside the estimator; scripts/finalize_search.py knows nothing about it.
    Its measured offsets are around 1e-4, so dropping it changes nothing.
    """
    cleaned = copy.deepcopy(info)
    cleaned["config"].pop("bias_correction", None)
    cleaned.setdefault("fit", {}).setdefault("best_epoch", cleaned["config"].get("epochs", 250))
    return fit_candidate(cleaned, training, protocol)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--members", type=int, default=10, help="ensemble size, chosen on validation")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    arguments = parser.parse_args()

    protocol, train, valid = load_pack()
    pool = candidates()
    if len(pool) < arguments.members:
        raise SystemExit(f"Only {len(pool)} candidates available; run the searches first")
    print(f"{len(pool)} candidates, best single {pool[0]['metrics']['mae']:.5f}")

    # Ensemble size is picked on validation only, like the single model was.
    options = []
    for count in (1, 3, 5, 10, 20):
        if count > len(pool):
            break
        prediction = np.mean([np.load(row["prediction_path"]) for row in pool[:count]], axis=0)
        options.append({"name": f"top_{count}_mean", "count": count,
                        "metrics": metrics(valid.power, prediction)})
        print(f"  top_{count}_mean: mae {options[-1]['metrics']['mae']:.5f}")
    chosen = min(options, key=lambda row: row["metrics"]["mae"])
    members = pool[: chosen["count"]]
    print(f"chosen: {chosen['name']}, validation mae {chosen['metrics']['mae']:.5f}")

    # The search pack deliberately excludes January, so the holdout is rebuilt
    # from the hourly data the same way scripts/finalize_search.py does it.
    offset = protocol["utc_offset_hours"]
    hourly, _ = load_hourly(timestamp_convention=protocol["timestamp_convention"])
    hourly["valid_time"] = (hourly.hour - pd.Timedelta(hours=offset)).dt.tz_localize("UTC")
    archive, _ = load_archive()
    scheduled = daily_schedule(archive, offset, 23)
    scheduled = scheduled.loc[
        scheduled.groupby(["as_of", "turbine_id"]).valid_time.transform("size").eq(48)
    ].copy()
    features = context_weather_features(scheduled)
    packed = pd.concat(
        [scheduled[["as_of", "valid_time", "turbine_id", "lead_hour"]], features.add_prefix("x_")], axis=1
    ).merge(hourly[["hour", "valid_time", "turbine_id", "power"]],
            on=["valid_time", "turbine_id"], validate="many_to_one")
    feature_columns = [c for c in packed if c.startswith("x_")]
    packed = packed.loc[
        (packed.hour >= "2024-03-02") & np.isfinite(packed[feature_columns].to_numpy()).all(axis=1)
    ].copy()

    holdout = period(packed, "2026-01", offset, 23)
    before_january = packed.loc[packed.hour < "2025-12-31"]
    contextual = any(row["config"]["features"] == "trajectory" for row in members)
    full_columns = protocol["features"] if contextual else protocol["point_features"]
    x_holdout = holdout[["x_" + c for c in full_columns]].rename(columns=lambda c: c[2:])
    print(f"refitting {len(members)} members on {len(before_january)} rows before January...")
    with threadpool_limits(limits=8):
        model = BlendRegressor([refit(info, before_january, protocol) for info in members])
    prediction = model.predict(x_holdout)
    january = score_groups(holdout, prediction)
    baseline_means = before_january.groupby("turbine_id").power.mean()
    baseline = metrics(holdout.power, holdout.turbine_id.map(baseline_means).to_numpy())

    OUTPUT.mkdir(parents=True, exist_ok=True)
    metadata = {
        "kind": "archived_weather_power_forecast",
        "winner": chosen["name"],
        "members": [{"name": row["name"], "origin": row["origin"], "config": row["config"],
                     "metrics": row["metrics"]} for row in members],
        "feature_set": members[0]["config"]["features"],
        "features": protocol["point_features"] if members[0]["config"]["features"] == "point"
                    else protocol["features"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "search": {"candidate_count": len(pool), "ensembles": options,
                   "january_used_for_search": False},
        "hardware": {"local_gpu": "RTX 5090 Laptop", "where": "local"},
        "january": january,
        "january_baseline": baseline,
        "validation": chosen["metrics"],
    }
    joblib.dump({"model": model, "metadata": metadata}, OUTPUT / "model.joblib", compress=3)
    (OUTPUT / "metrics.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str) + "\n")
    reduction = 100 * (1 - january["overall"]["mae"] / baseline["mae"])
    print(f"\nJanuary: mae {january['overall']['mae']:.5f}, bias {january['overall']['bias']:+.5f}")
    print(f"baseline: mae {baseline['mae']:.5f} — reduction {reduction:.1f}%")
    print(f"written: {OUTPUT}")


if __name__ == "__main__":
    main()
