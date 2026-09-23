"""Small CPU-compatible regressors, including a network trained on CUDA.

No PyTorch dependency at inference: the neural network exports plain NumPy
weights. Joblib artifacts must only be loaded from a trusted project source.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error


def metrics(actual: np.ndarray, prediction: np.ndarray) -> dict:
    actual, prediction = np.asarray(actual), np.clip(prediction, 0, 1)
    return {
        "n": len(actual), "mae": float(mean_absolute_error(actual, prediction)),
        "rmse": float(np.sqrt(mean_squared_error(actual, prediction))),
        "bias": float(np.mean(prediction - actual)),
    }


def observed_features(frame: pd.DataFrame) -> pd.DataFrame:
    """An observed-weather diagnostic, NOT a day-ahead forecast input table."""
    wind = frame.wind_speed
    temperature = frame.temperature
    return pd.DataFrame({
        "wind_speed": wind, "temperature": temperature,
        "density_adjusted_wind": wind * (288.15 / (273.15 + temperature)) ** (1 / 3),
        "turbine_id": frame.turbine_id,
    }, index=frame.index)


class TurbinePowerCurve:
    """Monotone empirical wind-to-power curve separately for each turbine."""

    def __init__(self, wind_column: str = "wind_speed"):
        self.wind_column = wind_column
        self.curves: dict[int, IsotonicRegression] = {}

    def fit(self, x: pd.DataFrame, y: np.ndarray):
        y = np.asarray(y)
        for turbine in (1, 2):
            mask = x.turbine_id.to_numpy() == turbine
            if not mask.any():
                raise ValueError(f"No training data for turbine {turbine}")
            self.curves[turbine] = IsotonicRegression(
                y_min=0, y_max=1, out_of_bounds="clip"
            ).fit(x.loc[mask, self.wind_column], y[mask])
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        prediction = np.full(len(x), np.nan)
        for turbine, curve in self.curves.items():
            mask = x.turbine_id.to_numpy() == turbine
            if mask.any():
                prediction[mask] = curve.predict(x.loc[mask, self.wind_column])
        if not np.isfinite(prediction).all():
            raise ValueError("Unknown turbine or invalid wind input")
        return prediction


@dataclass
class NumpyMLP:
    mean: np.ndarray
    scale: np.ndarray
    layers: list[tuple[np.ndarray, np.ndarray]]

    def predict(self, x: pd.DataFrame | np.ndarray) -> np.ndarray:
        values = (np.asarray(x, dtype=np.float32) - self.mean) / self.scale
        for index, (weight, bias) in enumerate(self.layers):
            values = values @ weight.T + bias
            if index < len(self.layers) - 1:
                values = np.maximum(values, 0)
        # The trained network has a sigmoid output, bounded to normalized power.
        return (1 / (1 + np.exp(-np.clip(values[:, 0], -40, 40)))).astype(float)


def fit_mlp(
    x: pd.DataFrame, y: np.ndarray,
    x_validation: pd.DataFrame | None = None, y_validation: np.ndarray | None = None,
    *, seed: int = 42, epochs: int = 160, device: str = "cuda",
    hidden: tuple[int, ...] = (64, 64, 32), loss_name: str = "mse",
    learning_rate: float = 0.001, weight_decay: float = 0.01,
    batch_size: int = 2048, patience: int = 25,
) -> tuple[NumpyMLP, dict]:
    """Train on GPU when requested; temporal validation controls early stopping.

    With no validation, fit exactly ``epochs`` (used for the final refit).
    January holdout must never be passed as validation to this function.
    """
    import torch

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable; use --device cpu")
    torch.set_num_threads(8)
    torch.manual_seed(seed)
    np.random.seed(seed)
    values = np.asarray(x, dtype=np.float32)
    mean = values.mean(axis=0)
    scale = values.std(axis=0).clip(1e-5)
    train_x = torch.as_tensor((values - mean) / scale, device=device)
    train_y = torch.as_tensor(np.asarray(y, dtype=np.float32), device=device)[:, None]
    if x_validation is not None:
        valid_x = torch.as_tensor(
            (np.asarray(x_validation, dtype=np.float32) - mean) / scale, device=device
        )
        valid_y = torch.as_tensor(np.asarray(y_validation, dtype=np.float32), device=device)[:, None]
    modules, input_size = [], values.shape[1]
    for size in hidden:
        modules.extend([torch.nn.Linear(input_size, size), torch.nn.ReLU()])
        input_size = size
    modules.extend([torch.nn.Linear(input_size, 1), torch.nn.Sigmoid()])
    network = torch.nn.Sequential(*modules).to(device)
    optimizer = torch.optim.AdamW(network.parameters(), lr=learning_rate, weight_decay=weight_decay)
    losses = {"mse": torch.nn.functional.mse_loss, "mae": torch.nn.functional.l1_loss,
              "huber": lambda a, b: torch.nn.functional.huber_loss(a, b, delta=0.1)}
    if loss_name not in losses:
        raise ValueError("Unknown loss")
    best_loss, best_epoch, best_state = float("inf"), 0, None
    started = time.monotonic()
    for epoch in range(epochs):
        network.train()
        order = torch.randperm(len(values), device=device)
        for indices in order.split(batch_size):
            optimizer.zero_grad(set_to_none=True)
            loss = losses[loss_name](network(train_x[indices]), train_y[indices])
            loss.backward()
            optimizer.step()
        if x_validation is not None:
            network.eval()
            with torch.no_grad():
                loss_value = float(torch.mean(torch.abs(network(valid_x) - valid_y)))
            if loss_value < best_loss - 0.00001:
                best_loss, best_epoch = loss_value, epoch + 1
                best_state = copy.deepcopy(network.state_dict())
            if epoch + 1 - best_epoch >= patience:
                break
        else:
            best_epoch = epoch + 1
    if best_state is not None:
        network.load_state_dict(best_state)
    network.eval()
    layers = [
        (layer.weight.detach().cpu().numpy().copy(), layer.bias.detach().cpu().numpy().copy())
        for layer in network if isinstance(layer, torch.nn.Linear)
    ]
    result = NumpyMLP(mean, scale, layers)
    return result, {
        "device": device, "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
        "best_epoch": best_epoch, "epochs_run": epoch + 1, "seed": seed,
        "hidden": list(hidden), "loss": loss_name, "learning_rate": learning_rate,
        "weight_decay": weight_decay, "batch_size": batch_size,
        "seconds": round(time.monotonic() - started, 2),
        "inference_backend": "numpy; no GPU or torch needed",
    }


def cpu_candidates(wind_column: str = "wind_speed") -> dict:
    return {
        "power_curve": TurbinePowerCurve(wind_column),
        "hist_boosting": HistGradientBoostingRegressor(
            max_iter=250, learning_rate=0.06, max_leaf_nodes=15,
            min_samples_leaf=60, l2_regularization=10, early_stopping=False, random_state=42,
        ),
        "extra_trees": ExtraTreesRegressor(
            n_estimators=200, max_depth=16, min_samples_leaf=16,
            max_features=0.9, n_jobs=8, random_state=42,
        ),
    }


def weather_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Only archived forecast fields and known calendar/turbine information.

    No target-time measured weather, power lags, interpolation from observations,
    or neighbouring forecast values from potentially later initializations.
    """
    result = pd.DataFrame(index=frame.index)
    result["turbine_id"] = frame.turbine_id.astype(float)
    result["forecast_offset_days"] = frame.forecast_offset_days.astype(float)
    valid = pd.to_datetime(frame.valid_time, utc=True)
    for name, values, period in [("hour", valid.dt.hour, 24), ("year", valid.dt.dayofyear, 365.25)]:
        result[f"{name}_sin"] = np.sin(values * 2 * np.pi / period)
        result[f"{name}_cos"] = np.cos(values * 2 * np.pi / period)
    for provider in ["gfs_global", "icon_global"]:
        prefix = provider + "_"
        wind = frame[prefix + "wind_speed_100m"]
        wind10 = frame[prefix + "wind_speed_10m"]
        temperature = frame[prefix + "temperature_2m"]
        pressure = frame[prefix + "surface_pressure"]
        radians = frame[prefix + "wind_direction_100m"] * np.pi / 180
        for variable in ["wind_speed_100m", "wind_speed_10m", "temperature_2m", "surface_pressure"]:
            result[prefix + variable] = frame[prefix + variable]
        result[prefix + "u100"] = -wind * np.sin(radians)
        result[prefix + "v100"] = -wind * np.cos(radians)
        result[prefix + "direction_sin"] = np.sin(radians)
        result[prefix + "direction_cos"] = np.cos(radians)
        result[prefix + "wind_shear"] = wind - wind10
        result[prefix + "density_adjusted_wind"] = wind * ((pressure / 1013.25) * (288.15 / (273.15 + temperature))) ** (1 / 3)
    result["models_wind_difference"] = frame.gfs_global_wind_speed_100m - frame.icon_global_wind_speed_100m
    return result.astype(float)


def context_weather_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Use the full weather trajectory already available at each issue.

    Adjacent hours are FORECASTS selected independently under the same as-of
    policy. Never shift along the fixed-offset archive before selecting as-of:
    that could pull a newer, unavailable cycle into the current issue.
    """
    if "as_of" not in frame or (frame.available_at_upper_bound > frame.as_of).any():
        raise ValueError("As-of-selected weather required for context features")
    result = weather_features(frame)
    result["lead_hour"] = frame.lead_hour.astype(float)
    ordered = frame.sort_values(["as_of", "turbine_id", "valid_time"])
    base = weather_features(ordered)
    grouping = [ordered.as_of, ordered.turbine_id]
    for provider in ["gfs_global", "icon_global"]:
        for variable in ["wind_speed_100m", "u100", "v100", "surface_pressure", "temperature_2m"]:
            col = provider + "_" + variable
            grouped = base[col].groupby(grouping)
            for lag in [-6, -3, 3, 6]:
                shifted = grouped.shift(lag)
                # At the edge, use the current forecast; no access to another issue.
                shifted = shifted.fillna(base[col])
                result[f"{col}_shift{lag:+d}"] = shifted.reindex(frame.index)
    for provider in ["gfs_global", "icon_global"]:
        col = provider + "_wind_speed_100m"
        grouped = base[col].groupby(grouping)
        for statistic in ["mean", "min", "max", "std"]:
            result[f"{col}_trajectory_{statistic}"] = grouped.transform(statistic).reindex(frame.index).fillna(0)
    return result.astype(float)


@dataclass
class FeatureRegressor:
    estimator: object
    columns: list[str]

    def fit(self, x: pd.DataFrame, y: np.ndarray):
        self.estimator.fit(x[self.columns], y)
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return np.clip(self.estimator.predict(x[self.columns]), 0, 1)


@dataclass
class BlendRegressor:
    estimators: list

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return np.mean([model.predict(x) for model in self.estimators], axis=0)


def predict_weather(bundle: dict, weather: pd.DataFrame) -> np.ndarray:
    metadata = bundle["metadata"]
    if metadata["kind"] != "archived_weather_power_forecast":
        raise ValueError("Expected a forecast model, not an observed-weather diagnostic")
    if "as_of" not in weather:
        raise ValueError("Forecast input must include as_of")
    if (weather.available_at_upper_bound > weather.as_of).any():
        raise ValueError("Forecast inputs violate the historical availability policy")
    cutoff = pd.Timestamp(metadata["training_data_available_until"])
    if (pd.to_datetime(weather.as_of, utc=True) < cutoff).any():
        raise ValueError("Model uses training targets unavailable at as_of")
    if metadata.get("feature_set") == "trajectory":
        counts = weather.groupby(["as_of", "turbine_id"]).valid_time.size()
        if not counts.eq(48).all():
            raise ValueError("Trajectory models require all 48 weather hours; trim predictions after inference")
        features = context_weather_features(weather)
    else:
        features = weather_features(weather)
    if list(features.columns) != metadata["features"] or not np.isfinite(features.to_numpy()).all():
        raise ValueError("Missing, non-finite or incompatible forecast features")
    prediction = np.clip(bundle["model"].predict(features), 0, 1)
    if not np.isfinite(prediction).all():
        raise ValueError("Non-finite model prediction")
    return prediction
