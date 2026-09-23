"""Read turbine telemetry and aggregate complete hours without imputing targets.

The source timezone is unknown. ``hour`` remains a naive source-clock label.
Weather joins require an explicit, recorded timezone assumption at the caller.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = {
    "ID": "id",
    "Статистическое время": "timestamp",
    "Средняя скорость ветра(m/s)": "wind_speed",
    "Нормализованная активная мощность": "power",
    "Средняя температура окружающей среды(°C)": "temperature",
}
TURBINES = {
    1: {"latitude": 43.645150, "longitude": 78.535604},
    2: {"latitude": 43.643198, "longitude": 78.538828},
}


def load_hourly(
    directory: str | Path = ROOT / "data/incoming",
    *,
    timestamp_convention: str = "start",
    min_samples: int = 6,
) -> tuple[pd.DataFrame, dict]:
    """Return hourly means and provenance. Interval convention is an assumption.

    ``start`` places 00:00..00:50 in [00:00, 01:00).
    ``end`` places 00:10..01:00 in [00:00, 01:00).
    The output label is always the start of the hour. No timezone is assigned.
    Empty and insufficiently covered hours are excluded, never zero filled.
    """
    if timestamp_convention not in {"start", "end"}:
        raise ValueError("timestamp_convention must be start or end")
    if not 1 <= min_samples <= 6:
        raise ValueError("min_samples must be between 1 and 6")
    frames, sources = [], []
    for turbine in TURBINES:
        path = Path(directory) / f"turbine_{turbine}.csv"
        raw = pd.read_csv(path)
        if set(raw.columns) != set(COLUMNS):
            raise ValueError(f"Unexpected columns: {path}")
        raw = raw.rename(columns=COLUMNS)
        raw["timestamp"] = pd.to_datetime(
            raw["timestamp"], format="%Y-%m-%d %H:%M:%S", errors="raise"
        )
        if raw["timestamp"].duplicated().any():
            raise ValueError(f"Duplicate timestamps: {path}")
        values = raw[["wind_speed", "temperature", "power"]].to_numpy(float)
        if not np.isfinite(values).all():
            raise ValueError(f"Missing or non-finite measurements: {path}")
        if not raw["power"].between(0, 1).all() or (raw.wind_speed < 0).any():
            raise ValueError(f"Out-of-range measurements: {path}")
        if ((raw.timestamp.dt.minute % 10 != 0) | (raw.timestamp.dt.second != 0)).any():
            raise ValueError(f"Measurements off the 10-minute grid: {path}")
        source_end = raw.timestamp.max()
        if timestamp_convention == "end":
            raw["timestamp"] -= pd.Timedelta(minutes=10)
        raw = raw.sort_values("timestamp").set_index("timestamp")
        grouped = raw.resample("h", label="left", closed="left")
        frame = grouped.agg(
            power=("power", "mean"), wind_speed=("wind_speed", "mean"),
            temperature=("temperature", "mean"), samples=("power", "count"),
        )
        frame["coverage"] = frame.samples / 6
        frame["available_at_source_clock"] = frame.index + pd.Timedelta(hours=1)
        sources.append({
            "turbine_id": turbine, "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source_rows": len(raw), "source_last_timestamp": str(source_end),
            "accepted_hours": int((frame.samples >= min_samples).sum()),
            "excluded_hours": int((frame.samples < min_samples).sum()),
        })
        frame = frame.loc[frame.samples >= min_samples].copy()
        frame["turbine_id"] = turbine
        frames.append(frame.rename_axis("hour").reset_index())
    result = pd.concat(frames, ignore_index=True).sort_values(["hour", "turbine_id"])
    return result.reset_index(drop=True), {
        "sources": sources, "timezone": "unspecified; source-clock labels retained",
        "timestamp_convention_assumption": timestamp_convention,
        "hour_label": "interval_start", "aggregation": "arithmetic mean",
        "minimum_samples_per_hour": min_samples, "target": "normalized_power",
        "missing_target_policy": "exclude incomplete hours; never impute",
    }
