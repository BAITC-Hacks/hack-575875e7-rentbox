"""Run the trained power forecast on cached weather, without keys or a GPU."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib

from src.data import ROOT
from src.model import predict_weather
from src.weather import load_archive, select_as_of


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="Timezone-aware issue timestamp")
    parser.add_argument("--horizon", type=int, choices=[24, 48], default=48)
    parser.add_argument("--model", type=Path, default=ROOT / "artifacts/forecast/model.joblib")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/prediction.csv")
    args = parser.parse_args()
    bundle = joblib.load(args.model)
    archive, _ = load_archive()
    # Context models always see their trained 48-hour trajectory, then trim output.
    calculation_horizon = 48 if bundle["metadata"].get("feature_set") == "trajectory" else args.horizon
    selected = select_as_of(archive, args.as_of, calculation_horizon)
    selected["predicted_power"] = predict_weather(bundle, selected)
    selected = selected.loc[selected.lead_hour <= args.horizon]
    columns = ["as_of", "turbine_id", "valid_time", "lead_hour", "predicted_power", "forecast_offset_days", "available_at_upper_bound"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    selected[columns].to_csv(args.output, index=False)
    print(json.dumps({"output": str(args.output), "rows": len(selected), "model": bundle["metadata"]["winner"],
                      "time_assumptions": bundle["metadata"]["time_assumptions"],
                      "weather_note": "Fixed forecast offsets; availability upper bound uses a 12-hour policy margin."}, ensure_ascii=False))


if __name__ == "__main__":
    main()
