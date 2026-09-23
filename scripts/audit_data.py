"""Inspect the original turbine CSV files without filling gaps or shifting time.

Run from the repository root with an environment containing pandas and numpy:
    python scripts/audit_data.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


COLUMNS = {
    "ID": "id",
    "Статистическое время": "timestamp",
    "Средняя скорость ветра(m/s)": "wind_speed",
    "Нормализованная активная мощность": "power",
    "Средняя температура окружающей среды(°C)": "temperature",
}


def inspect(path: Path) -> dict:
    frame = pd.read_csv(path)
    if set(frame.columns) != set(COLUMNS):
        raise ValueError(f"Unexpected columns in {path.name}: {list(frame.columns)}")
    frame = frame.rename(columns=COLUMNS)
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"], format="%Y-%m-%d %H:%M:%S", errors="raise"
    )
    ordered = bool(frame["timestamp"].is_monotonic_increasing)
    frame = frame.sort_values("timestamp").set_index("timestamp")
    expected = pd.date_range(frame.index.min(), frame.index.max(), freq="10min")
    missing = expected.difference(frame.index)
    hourly_counts = frame.resample("h").size()
    step = pd.Timedelta(minutes=10)
    differences = frame.index.to_series().diff()
    gaps = differences[differences > step].sort_values(ascending=False)
    measurements = frame[["wind_speed", "power", "temperature"]]
    january = frame.loc["2026-01"]
    return {
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rows": len(frame),
        "start": str(frame.index.min()),
        "end": str(frame.index.max()),
        "timezone": "unspecified in source",
        "sorted_in_file": ordered,
        "duplicate_timestamps": int(frame.index.duplicated().sum()),
        "missing_values": int(frame.isna().sum().sum()),
        "nonfinite_measurements": int((~np.isfinite(measurements.to_numpy())).sum()),
        "off_grid_timestamps": int(
            ((frame.index.minute % 10 != 0) | (frame.index.second != 0)).sum()
        ),
        "expected_10min_records": len(expected),
        "missing_10min_records": len(missing),
        "missing_percent": round(len(missing) / len(expected) * 100, 3),
        "full_hours": int((hourly_counts == 6).sum()),
        "partial_hours": int(((hourly_counts > 0) & (hourly_counts < 6)).sum()),
        "empty_hours": int((hourly_counts == 0).sum()),
        "negative_wind_records": int((frame["wind_speed"] < 0).sum()),
        "power_outside_0_1": int(((frame["power"] < 0) | (frame["power"] > 1)).sum()),
        "unique_power_values": int(frame["power"].nunique()),
        "statistics": measurements.describe(percentiles=[0.01, 0.5, 0.99]).round(4).to_dict(),
        "largest_gaps": [
            {
                "last_observation": str(end - gap),
                "next_observation": str(end),
                "missing_records": int(gap / step) - 1,
            }
            for end, gap in gaps.head(10).items()
        ],
        "january_2026_records": len(january),
        "january_2026_complete": len(january) == 31 * 24 * 6
        and january.index.is_unique,
        "records_from_february_2026": int((frame.index >= pd.Timestamp("2026-02-01")).sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/incoming"))
    parser.add_argument("--output", type=Path, default=Path("reports/data-audit.json"))
    arguments = parser.parse_args()
    paths = sorted(arguments.input.glob("*.csv"))
    if not paths:
        parser.error(f"No CSV files in {arguments.input}")
    result = {
        "scope": "Original source data only; no interpolation, timezone assignment or training",
        "turbines": [inspect(path) for path in paths],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    for turbine in result["turbines"]:
        print(
            f"{turbine['file']}: {turbine['rows']} records, "
            f"{turbine['missing_10min_records']} missing timestamps "
            f"({turbine['missing_percent']}%), "
            f"{turbine['full_hours']} full hours"
        )
    print(f"Report: {arguments.output}")


if __name__ == "__main__":
    main()
