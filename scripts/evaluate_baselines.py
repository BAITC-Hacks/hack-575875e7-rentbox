"""Compare a forecast CSV with means and strictly as-of persistence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.data import ROOT, load_hourly
from src.model import metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=ROOT / "artifacts/forecast/january_predictions.csv")
    parser.add_argument("--utc-offset", type=int, required=True)
    parser.add_argument("--timestamp-convention", choices=["start", "end"], required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/persistence-baseline.json")
    args = parser.parse_args()
    hourly, _ = load_hourly(timestamp_convention=args.timestamp_convention)
    hourly["available_at"] = (hourly.hour + pd.Timedelta(hours=1-args.utc_offset)).dt.tz_localize("UTC")
    predictions = pd.read_csv(args.predictions, parse_dates=["as_of", "valid_time"])
    tables = []
    for turbine, part in predictions.groupby("turbine_id"):
        observations = hourly.loc[hourly.turbine_id == turbine, ["available_at", "power"]].rename(columns={"power": "persistence_power"})
        tables.append(pd.merge_asof(part.sort_values("as_of"), observations.sort_values("available_at"),
                                   left_on="as_of", right_on="available_at", direction="backward", allow_exact_matches=True))
    result = pd.concat(tables, ignore_index=True)
    # "Yesterday at this hour" must not read future telemetry at leads 25..48.
    # Choose the latest SAME clock hour whose complete mean existed at as_of.
    lag_days = np.ceil((result.valid_time + pd.Timedelta(hours=1) - result.as_of).dt.total_seconds() / 86400).astype(int)
    result["seasonal_source_available_at"] = result.valid_time + pd.Timedelta(hours=1) - pd.to_timedelta(lag_days, unit="D")
    source = hourly[["turbine_id", "available_at", "power"]].rename(columns={"available_at": "seasonal_source_available_at", "power": "seasonal_power"})
    result = result.merge(source, on=["turbine_id", "seasonal_source_available_at"], how="left", validate="many_to_one")
    seasonal_valid = result.seasonal_power.notna()
    report = {
        "time_assumptions": {"utc_offset_hours": args.utc_offset, "timestamp_convention": args.timestamp_convention},
        "persistence_definition": "Last completed hourly power available at as_of, constant over horizon",
        "overall": metrics(result.power, result.persistence_power),
        "model": metrics(result.power, result.predicted_power),
        "seasonal_persistence": metrics(result.loc[seasonal_valid, "power"], result.loc[seasonal_valid, "seasonal_power"]),
        "seasonal_missing_hours": int((~seasonal_valid).sum()),
        "seasonal_definition": "Latest same clock hour fully available at as_of; 24/48/72h lag, never future telemetry",
        "by_horizon": {label: metrics(part.power, part.persistence_power) for label, part in [
            ("1-24h", result.loc[result.lead_hour <= 24]), ("25-48h", result.loc[result.lead_hour > 24])]},
        "note": "January telemetry revealed only up to each issue. No February actuals; persistence becomes stale in February.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
