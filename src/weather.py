"""Cached archived forecast offsets from Open-Meteo, never reanalysis.

Previous Runs contains fixed forecast offsets, not whole individual cycles.
We store that distinction and an availability upper bound, not invented run IDs.
Source: https://open-meteo.com/en/docs/previous-runs-api
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from src.data import ROOT, TURBINES

ENDPOINT = "https://previous-runs-api.open-meteo.com/v1/forecast"
VARIABLES = ("temperature_2m", "wind_speed_10m", "wind_speed_100m", "wind_direction_100m", "surface_pressure")
MODELS = ("gfs_global", "icon_global")
OFFSETS = (1, 2, 3)
CACHE = ROOT / "data/weather"
# Conservative extra time for model computation, ingestion and cycle rounding.
# This is a policy assumption, NOT measured historical provider latency.
PUBLICATION_MARGIN_HOURS = 12


def fetch_month(model: str, month: str, *, cache: Path = CACHE, refresh: bool = False) -> Path:
    if model not in MODELS:
        raise ValueError(f"Unsupported weather model: {model}")
    start = pd.Period(month, freq="M").start_time
    end = pd.Period(month, freq="M").end_time
    params = {
        "latitude": ",".join(str(t["latitude"]) for t in TURBINES.values()),
        "longitude": ",".join(str(t["longitude"]) for t in TURBINES.values()),
        "start_date": start.strftime("%Y-%m-%d"), "end_date": end.strftime("%Y-%m-%d"),
        "hourly": ",".join(f"{v}_previous_day{d}" for d in OFFSETS for v in VARIABLES),
        "models": model, "wind_speed_unit": "ms", "timezone": "UTC",
    }
    directory = Path(cache) / model
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{month}.json"
    metadata_path = directory / f"{month}.meta.json"
    if path.exists() and metadata_path.exists() and not refresh:
        meta = json.loads(metadata_path.read_text())
        if meta["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest() and meta["params"] == params:
            return path
        raise ValueError(f"Weather cache integrity/parameters mismatch: {path}")
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for attempt in range(4):
            try:
                response = client.get(ENDPOINT, params=params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list) or len(payload) != len(TURBINES):
                    raise ValueError("Weather API returned an unexpected location count")
                for location in payload:
                    if location["hourly_units"].get("wind_speed_100m_previous_day1") != "m/s":
                        raise ValueError("Weather API wind units must be m/s")
                    if location.get("utc_offset_seconds") != 0:
                        raise ValueError("Weather API timestamps must be UTC")
                raw = response.content
                metadata = {
                    "endpoint": ENDPOINT, "params": params,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "provider": "Open-Meteo", "model": model,
                    "product": "fixed lead offsets; not a single initialization",
                    "documentation": "https://open-meteo.com/en/docs/previous-runs-api",
                    "license": "CC BY 4.0; credit Open-Meteo and NOAA/DWD",
                    "initialization_time": None,
                    "availability_basis": "valid_time - previous_day * 24h + 12h policy margin",
                }
                temporary = path.with_suffix(".json.tmp")
                temporary.write_bytes(raw)
                temporary.replace(path)
                metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
                return path
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in {429, 500, 502, 503, 504}:
                    raise
                if attempt == 3:
                    raise
                time.sleep(min(2 ** (attempt + 1), 15))
    raise RuntimeError("Weather request failed")


def load_archive(cache: Path = CACHE, models: tuple[str, ...] = MODELS) -> tuple[pd.DataFrame, list[dict]]:
    tables, manifests = [], []
    for model in models:
        monthly = []
        for path in sorted((Path(cache) / model).glob("????-??.json")):
            metadata_path = path.with_suffix(".meta.json")
            metadata = json.loads(metadata_path.read_text())
            if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]:
                raise ValueError(f"Weather checksum mismatch: {path}")
            payload = json.loads(path.read_bytes())
            manifests.append({"file": str(path.relative_to(cache)), "sha256": metadata["sha256"],
                              "retrieved_at": metadata["retrieved_at"], "model": model})
            for turbine, location in zip(TURBINES, payload, strict=True):
                hourly = location["hourly"]
                for offset in OFFSETS:
                    frame = pd.DataFrame({
                        "valid_time": pd.to_datetime(hourly["time"], utc=True),
                        "turbine_id": turbine, "forecast_offset_days": offset,
                        **{f"{model}_{v}": np.asarray(hourly[f"{v}_previous_day{offset}"], dtype=float) for v in VARIABLES},
                    })
                    monthly.append(frame)
        if not monthly:
            raise ValueError(f"No cached weather for {model}. Run python -m src.weather first.")
        table = pd.concat(monthly, ignore_index=True)
        if table.duplicated(["valid_time", "turbine_id", "forecast_offset_days"]).any():
            raise ValueError("Duplicate archived weather keys")
        tables.append(table)
    joined = tables[0]
    for table in tables[1:]:
        joined = joined.merge(table, on=["valid_time", "turbine_id", "forecast_offset_days"], validate="one_to_one", how="outer")
    joined["available_at_upper_bound"] = (
        joined.valid_time - pd.to_timedelta(joined.forecast_offset_days * 24, unit="h")
        + pd.Timedelta(hours=PUBLICATION_MARGIN_HOURS)
    )
    return joined.sort_values(["valid_time", "turbine_id", "forecast_offset_days"]).reset_index(drop=True), manifests


def select_as_of(archive: pd.DataFrame, as_of: str | pd.Timestamp, horizon_hours: int = 48) -> pd.DataFrame:
    """Select the youngest permitted offset per future hour; no day0 values.

    The result can contain several underlying cycles. ``available_at_upper_bound``
    is derived from documented offset semantics plus the policy margin.
    Exact historical publication timestamps are not exposed by this API.
    """
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        raise ValueError("as_of needs an explicit timezone")
    if as_of != as_of.floor("h") or horizon_hours not in {24, 48}:
        raise ValueError("as_of must be on an hour boundary; horizon must be 24 or 48")
    wanted = pd.date_range(as_of + pd.Timedelta(hours=1), periods=horizon_hours, freq="h")
    selected = archive.loc[
        archive.valid_time.isin(wanted) & (archive.available_at_upper_bound <= as_of)
    ].sort_values("forecast_offset_days").drop_duplicates(["valid_time", "turbine_id"])
    expected = len(TURBINES) * horizon_hours
    if len(selected) != expected:
        raise ValueError(f"WEATHER_UNAVAILABLE: expected {expected} forecast points, got {len(selected)}")
    weather_columns = [c for c in selected if any(c.startswith(f"{m}_") for m in MODELS)]
    if not np.isfinite(selected[weather_columns].to_numpy(float)).all():
        raise ValueError("WEATHER_UNAVAILABLE: missing values in selected forecast offsets")
    selected = selected.copy()
    selected["as_of"] = as_of
    selected["lead_hour"] = ((selected.valid_time - as_of).dt.total_seconds() / 3600).astype(int)
    return selected.sort_values(["turbine_id", "valid_time"]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2024-01")
    parser.add_argument("--end", default="2026-03")
    parser.add_argument("--models", nargs="+", default=list(MODELS), choices=list(MODELS))
    args = parser.parse_args()
    for month in pd.period_range(args.start, args.end, freq="M"):
        for model in args.models:
            path = fetch_month(model, str(month))
            print(f"{model} {month}: {path.stat().st_size} bytes cached", flush=True)
    archive, manifests = load_archive(models=tuple(args.models))
    output = CACHE / "archive.parquet"
    archive.to_parquet(output, index=False)
    (CACHE / "manifest.json").write_text(json.dumps(manifests, indent=2) + "\n")
    print(f"Saved {len(archive)} forecast-offset rows to {output}", flush=True)


if __name__ == "__main__":
    main()
