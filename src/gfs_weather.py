"""Read archived operational GFS cycles and enforce publication cutoffs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.data import ROOT

CACHE = ROOT / "data/gfs-runs"


def load_runs(cache: Path = CACHE, days: list[str] | None = None) -> tuple[pd.DataFrame, list[dict]]:
    frames, manifests = [], []
    paths = [cache / (day + ".csv") for day in days] if days is not None else sorted(cache.glob("????-??-??.csv"))
    for path in paths:
        metadata = json.loads(path.with_suffix(".meta.json").read_text())
        if metadata["resolution"] != "0p25":
            raise ValueError("The production model requires the GFS 0.25-degree grid")
        if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]:
            raise ValueError(f"NOAA point cache checksum mismatch: {path.name}")
        as_of, initialization, available = [pd.Timestamp(metadata[k]) for k in ("as_of", "initialization_time", "available_at")]
        if any(t.tzinfo is None for t in (as_of, initialization, available)):
            raise ValueError("NOAA provenance timestamps require UTC offsets")
        if not initialization <= available <= as_of:
            raise ValueError("NOAA run was unavailable at the historical decision time")
        sources = metadata["sources"]
        if len(sources) != 17 or {s["forecast_hour"] for s in sources} != set(range(6, 55, 3)):
            raise ValueError("NOAA provenance must cover every interpolation anchor")
        for source in sources:
            if pd.Timestamp(source["initialization_time"]) != initialization or pd.Timestamp(source["available_at"]) > as_of:
                raise ValueError("Mixed cycles or unavailable GRIB object")
            if len(source["byte_ranges"]) != 6 or not source["url"].startswith("https://noaa-gfs-bdp-pds.s3.amazonaws.com/"):
                raise ValueError("Incomplete NOAA source provenance")
        frame = pd.read_csv(path)
        for column in ("as_of", "valid_time", "initialization_time", "available_at"):
            frame[column] = pd.to_datetime(frame[column], utc=True)
        if len(frame) != 96 or frame.duplicated(["turbine_id", "valid_time"]).any():
            raise ValueError("NOAA run must contain 48 hours for each turbine")
        if set(frame.turbine_id) != {1, 2} or not frame.as_of.eq(as_of).all():
            raise ValueError("NOAA run identity mismatch")
        if not frame.initialization_time.eq(initialization).all() or not frame.available_at.eq(available).all():
            raise ValueError("NOAA timestamps do not match the manifest")
        for _, group in frame.groupby("turbine_id"):
            if sorted(group.lead_hour) != list(range(1, 49)):
                raise ValueError("Incomplete NOAA lead hours")
        if not frame.valid_time.eq(frame.as_of + pd.to_timedelta(frame.lead_hour, unit="h")).all():
            raise ValueError("NOAA target times do not match forecast lead")
        numeric = ["u10", "v10", "u100", "v100", "temperature_2m", "surface_pressure", "wind_speed_10m", "wind_speed_100m"]
        if not np.isfinite(frame[numeric].to_numpy()).all():
            raise ValueError("Missing NOAA weather values")
        frames.append(frame)
        manifests.append({"file": path.name, **metadata})
    if not frames:
        raise ValueError("No NOAA GFS archive is available")
    return pd.concat(frames, ignore_index=True), manifests


def select_run(as_of: str | pd.Timestamp, cache: Path = CACHE) -> tuple[pd.DataFrame, dict]:
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        raise ValueError("as_of requires a timezone")
    frame, manifests = load_runs(cache, [as_of.tz_convert("UTC").strftime("%Y-%m-%d")])
    if not frame.as_of.eq(as_of).all():
        raise ValueError("The cached GFS cycle belongs to another decision time")
    return frame, manifests[0]
