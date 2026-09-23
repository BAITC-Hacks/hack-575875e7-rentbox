"""Run the trained power forecast on cached weather, without keys or a GPU."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
from threadpoolctl import threadpool_limits

from src.data import ROOT
from src.gfs_model import predict as predict_gfs
from src.gfs_weather import select_run
from src.model import predict_weather
from src.weather import load_archive, select_as_of


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="Timezone-aware issue timestamp")
    parser.add_argument("--horizon", type=int, choices=[24, 48], default=48)
    parser.add_argument("--model", type=Path, default=ROOT / "artifacts/gfs-model/model.joblib")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/prediction.csv")
    args = parser.parse_args()
    bundle = joblib.load(args.model)
    columns = ["as_of", "turbine_id", "valid_time", "lead_hour", "predicted_power"]
    with threadpool_limits(limits=2):
        if bundle["metadata"]["kind"] == "noaa_gfs_operational_forecast":
            # Always calculate the full cycle before trimming a 24-hour request.
            selected, _ = select_run(args.as_of)
            selected["predicted_power"] = predict_gfs(bundle, selected)
            columns += ["initialization_time", "available_at"]
            weather_note = "NOAA GFS cycle; original source object Last-Modified <= as_of."
        else:
            archive, _ = load_archive()
            calculation_horizon = 48 if bundle["metadata"].get("feature_set") == "trajectory" else args.horizon
            selected = select_as_of(archive, args.as_of, calculation_horizon)
            selected["predicted_power"] = predict_weather(bundle, selected)
            columns += ["forecast_offset_days", "available_at_upper_bound"]
            weather_note = "Fixed forecast offsets; availability upper bound uses an assumed 12-hour margin."
    selected = selected.loc[selected.lead_hour <= args.horizon]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    selected[columns].to_csv(args.output, index=False)
    print(json.dumps({"output": str(args.output), "rows": len(selected), "model": bundle["metadata"]["winner"],
                      "time_assumptions": bundle["metadata"]["time_assumptions"],
                      "weather_note": weather_note}, ensure_ascii=False))


if __name__ == "__main__":
    main()
