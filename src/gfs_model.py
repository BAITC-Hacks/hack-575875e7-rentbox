"""Features and CPU inference for single-cycle operational NOAA GFS forecasts."""

from __future__ import annotations

import numpy as np
import pandas as pd


def features(frame: pd.DataFrame, trajectory: bool = False) -> pd.DataFrame:
    if (frame.available_at > frame.as_of).any() or (frame.initialization_time > frame.available_at).any():
        raise ValueError("NOAA weather violates historical availability")
    result = frame[["turbine_id", "lead_hour", "u10", "v10", "u100", "v100", "temperature_2m",
                    "surface_pressure", "wind_speed_10m", "wind_speed_100m"]].astype(float).copy()
    for name, value, period in [("hour", frame.valid_time.dt.hour, 24), ("year", frame.valid_time.dt.dayofyear, 365.25)]:
        result[name + "_sin"] = np.sin(value * 2 * np.pi / period)
        result[name + "_cos"] = np.cos(value * 2 * np.pi / period)
    result["nwp_lead_hour"] = (frame.valid_time - frame.initialization_time).dt.total_seconds() / 3600
    density = frame.surface_pressure * 100 / (287.05 * (frame.temperature_2m + 273.15))
    result["air_density"] = density
    result["density_adjusted_wind"] = frame.wind_speed_100m * (density / 1.225) ** (1 / 3)
    result["wind_power_density"] = density * frame.wind_speed_100m ** 3
    result["wind_shear"] = frame.wind_speed_100m - frame.wind_speed_10m
    result["direction_sin"] = -frame.u100 / frame.wind_speed_100m.clip(lower=0.01)
    result["direction_cos"] = -frame.v100 / frame.wind_speed_100m.clip(lower=0.01)
    result["freezing_distance"] = abs(frame.temperature_2m)
    if trajectory:
        if not frame.groupby(["as_of", "turbine_id"]).valid_time.size().eq(48).all():
            raise ValueError("Trajectory features require the full 48-hour cycle")
        ordered = frame.sort_values(["as_of", "turbine_id", "valid_time"])
        grouped = ordered.groupby(["as_of", "turbine_id"], sort=False)
        for column in ["wind_speed_100m", "u100", "v100", "temperature_2m", "surface_pressure"]:
            for shift in [-6, -3, 3, 6]:
                result[f"{column}_shift{shift}"] = grouped[column].shift(shift).fillna(ordered[column]).reindex(frame.index)
        for aggregate in ["mean", "std", "min", "max"]:
            result["wind_trajectory_" + aggregate] = grouped.wind_speed_100m.transform(aggregate).reindex(frame.index)
    return result.astype(float)


def predict(bundle: dict, weather: pd.DataFrame) -> np.ndarray:
    metadata = bundle["metadata"]
    if metadata["kind"] != "noaa_gfs_operational_forecast":
        raise ValueError("Expected a model trained on operational GFS cycles")
    if (weather.as_of < pd.Timestamp(metadata["training_data_available_until"])).any():
        raise ValueError("Model training includes targets unavailable at as_of")
    values = features(weather, trajectory=metadata["feature_set"] == "trajectory")
    if list(values.columns) != metadata["features"] or not np.isfinite(values.to_numpy()).all():
        raise ValueError("Incompatible GFS forecast features")
    power = np.asarray(bundle["model"].predict(values))
    if not np.isfinite(power).all():
        raise ValueError("Non-finite power prediction")
    return np.clip(power, 0, 1)
