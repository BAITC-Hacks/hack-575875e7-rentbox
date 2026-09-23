"""Archive actual NOAA GFS cycles with S3 publication evidence, no reanalysis.

Download only six GRIB fields, extract turbine points and discard global arrays.
Three-hourly forecast anchors from the SAME cycle are interpolated to hours.
Every contributing S3 object's Last-Modified must be <= the historical as_of.
ecCodes is an optional acquisition dependency, never needed for cached inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from src.data import ROOT, TURBINES

BASE = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
FIELDS = {("UGRD", "10 m above ground"): "u10", ("VGRD", "10 m above ground"): "v10",
          ("UGRD", "100 m above ground"): "u100", ("VGRD", "100 m above ground"): "v100",
          ("TMP", "2 m above ground"): "temperature_2m", ("PRES", "surface"): "surface_pressure"}


def get(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    for attempt in range(4):
        try:
            response = client.get(url, **kwargs)
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.HTTPStatusError) as error:
            if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in {429, 500, 502, 503, 504}:
                raise
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Unreachable")


def fetch_anchor(client: httpx.Client, initialization: pd.Timestamp, lead: int,
                 as_of: pd.Timestamp, resolution: str) -> tuple[list[dict], dict]:
    import eccodes

    stamp = initialization.strftime("%Y%m%d")
    cycle = initialization.strftime("%H")
    url = f"{BASE}/gfs.{stamp}/{cycle}/atmos/gfs.t{cycle}z.pgrb2.{resolution}.f{lead:03d}"
    index = get(client, url + ".idx")
    entries = [line.split(":") for line in index.text.splitlines() if line]
    wanted = []
    for i, entry in enumerate(entries):
        name = FIELDS.get((entry[3], entry[4]))
        if name is not None:
            wanted.append((int(entry[1]), int(entries[i+1][1])-1, name))
    if len(wanted) != len(FIELDS):
        raise ValueError(f"Missing GFS fields at {url}")
    valid_time = initialization + pd.Timedelta(hours=lead)
    rows = {t: {"turbine_id": t, "valid_time": valid_time.isoformat()} for t in TURBINES}
    ranges, availability, etags = [], [], set()
    for start, end, name in wanted:
        response = get(client, url, headers={"Range": f"bytes={start}-{end}"})
        if response.status_code != 206 or len(response.content) != end-start+1:
            raise ValueError("NOAA did not honor the byte range")
        published = pd.Timestamp(parsedate_to_datetime(response.headers["last-modified"]))
        if published > as_of or published < initialization:
            raise ValueError(f"Object was not available at issue: {url}, {published}, {as_of}")
        availability.append(published)
        etags.add(response.headers.get("etag"))
        gid = eccodes.codes_new_from_message(response.content)
        try:
            date, hour = eccodes.codes_get(gid, "dataDate"), eccodes.codes_get(gid, "dataTime")
            forecast_hour = eccodes.codes_get(gid, "forecastTime")
            if date != int(stamp) or hour != int(cycle)*100 or forecast_hour != lead:
                raise ValueError("GRIB cycle/lead does not match request")
            for turbine, coordinates in TURBINES.items():
                nearest = eccodes.codes_grib_find_nearest(gid, coordinates["latitude"], coordinates["longitude"])[0]
                value = float(nearest["value"])
                if not np.isfinite(value) or abs(value) > 1e10:
                    raise ValueError("Missing GRIB value")
                rows[turbine][name] = value
                rows[turbine]["grid_latitude"] = float(nearest["lat"])
                rows[turbine]["grid_longitude"] = float(nearest["lon"])
        finally:
            eccodes.codes_release(gid)
        ranges.append({"field": name, "start": start, "end": end,
                       "sha256": hashlib.sha256(response.content).hexdigest()})
    if len(etags) != 1:
        raise ValueError("The source object changed while downloading fields")
    return list(rows.values()), {"url": url, "initialization_time": initialization.isoformat(),
        "forecast_hour": lead, "available_at": max(availability).isoformat(), "etag": etags.pop(),
        "index_sha256": hashlib.sha256(index.content).hexdigest(), "byte_ranges": ranges}


def fetch_day(day: pd.Timestamp, output: Path, resolution: str, executor: ThreadPoolExecutor,
              client: httpx.Client, *, refresh: bool = False) -> dict:
    key = day.strftime("%Y-%m-%d")
    csv = output / f"{key}.csv"
    manifest = output / f"{key}.meta.json"
    if csv.exists() and manifest.exists() and not refresh:
        saved = json.loads(manifest.read_text())
        if saved["sha256"] != hashlib.sha256(csv.read_bytes()).hexdigest():
            raise ValueError("GFS point cache checksum mismatch")
        return saved
    as_of = day.tz_localize("UTC") + pd.Timedelta(hours=18)
    # 12 UTC GFS cycle, decision 18 UTC, first target 19 UTC.
    initialization = as_of - pd.Timedelta(hours=6)
    futures = [executor.submit(fetch_anchor, client, initialization, lead, as_of, resolution)
               for lead in range(6, 55, 3)]
    records, sources = [], []
    for future in as_completed(futures):
        values, source = future.result()
        records.extend(values)
        sources.append(source)
    anchors = pd.DataFrame(records)
    anchors["valid_time"] = pd.to_datetime(anchors.valid_time, utc=True)
    hourly = []
    wanted_times = pd.date_range(as_of + pd.Timedelta(hours=1), periods=48, freq="h")
    for turbine, group in anchors.groupby("turbine_id"):
        group = group.set_index("valid_time").sort_index()
        target = group.reindex(group.index.union(wanted_times)).interpolate(method="time").loc[wanted_times].copy()
        target.index.name = "valid_time"
        target["temperature_2m"] -= 273.15
        target["surface_pressure"] /= 100
        target["wind_speed_10m"] = np.hypot(target.u10, target.v10)
        target["wind_speed_100m"] = np.hypot(target.u100, target.v100)
        target["wind_direction_100m"] = np.degrees(np.arctan2(-target.u100, -target.v100)) % 360
        target["turbine_id"] = int(turbine)
        target["as_of"] = as_of
        target["initialization_time"] = initialization
        target["available_at"] = max(pd.Timestamp(s["available_at"]) for s in sources)
        target["lead_hour"] = np.arange(1, 49)
        hourly.append(target.reset_index())
    frame = pd.concat(hourly, ignore_index=True)
    temporary = csv.with_suffix(".csv.tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(csv)
    metadata = {"provider": "NOAA GFS operational forecast archive", "resolution": resolution,
        "as_of": as_of.isoformat(), "initialization_time": initialization.isoformat(),
        "available_at": frame.available_at.max().isoformat(),
        "availability_basis": "Maximum original S3 Last-Modified of all contributing GRIB objects; checked <= as_of",
        "interpolation": "Nearest spatial grid point; linear time interpolation of same-cycle 3-hour forecast anchors, never observations",
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "rows": len(frame),
        "sha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
        "sources": sorted(sources, key=lambda x:x["forecast_hour"])}
    manifest.write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--resolution", choices=["0p25", "0p50", "1p00"], default="0p25")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--output", type=Path, default=ROOT / "data/gfs-runs")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    failures = []
    with httpx.Client(timeout=45, limits=httpx.Limits(max_connections=args.workers*2)) as client, \
            ThreadPoolExecutor(max_workers=args.workers) as executor:
        for day in pd.date_range(args.start, args.end, freq="D"):
            started = time.monotonic()
            try:
                result = fetch_day(day, args.output, args.resolution, executor, client)
                print(json.dumps({"day": str(day.date()), "rows": result["rows"],
                                  "available_at": result["available_at"], "seconds": round(time.monotonic()-started,2)}), flush=True)
            except Exception as error:  # noqa: BLE001 -- retain failed days for a resumable archive download
                failures.append({"day": str(day.date()), "error": str(error)})
                print(json.dumps(failures[-1]), flush=True)
    (args.output / f"download-failures-{args.start}-{args.end}.json").write_text(json.dumps(failures, indent=2) + "\n")
    if failures:
        raise SystemExit(f"{len(failures)} days failed; rerun to retry")


if __name__ == "__main__":
    main()
