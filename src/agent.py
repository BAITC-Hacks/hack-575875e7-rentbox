"""Forecast tools and policy controller, integrated with the team's HTTP backend."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from backend.app.core.errors import AppError
from backend.app.integrations.forecasting import AgentContext
from backend.app.schemas.forecast import (
    AgentResult,
    AgentUpdate,
    ComputedSeries,
    ForecastAnalysis,
    ForecastPoint,
    ForecastRunCreate,
    WeatherProvenance,
)
from backend.app.schemas.weather import (
    PreviousRunsWeatherSource,
    SingleRunWeatherSource,
    WeatherInput,
)
from src.data import ROOT, TURBINES
from src.model import predict_weather
from src.weather import CACHE, MODELS, fetch_month, load_archive, select_as_of


WEATHER_FIELDS = ("wind_speed_100m", "wind_speed_10m", "temperature_2m")


def point_weather(row, prefixes: tuple[str, ...] = ("",)) -> dict[str, float]:
    """Weather values for one hour, averaged across the given column prefixes."""
    return {field: round(float(np.mean([getattr(row, prefix + field) for prefix in prefixes])), 3)
            for field in WEATHER_FIELDS}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


class ForecastAgent:
    mode = "policy"

    def __init__(self, model_dir: Path | None = None, cache: Path | None = None):
        configured = os.environ.get("RENTBOX_MODEL_DIR")
        self.model_dir = model_dir or (Path(configured) if configured else None)
        self.cache = cache or Path(os.environ.get("RENTBOX_WEATHER_CACHE", ROOT / "data/weather-runtime"))

    def run(self, request: ForecastRunCreate, context: AgentContext) -> AgentResult:
        def emit(stage, progress, message, tool=None, level="info"):
            if context.cancelled():
                raise AppError(503, "JOB_INTERRUPTED", "Расчёт прерван остановкой сервера.", retryable=True)
            context.emit(AgentUpdate(stage=stage, progress=progress, message=message,
                                     tool=tool, level=level, agent_mode="policy"))

        as_of = pd.Timestamp(request.as_of)
        if as_of != as_of.floor("h"):
            raise AppError(422, "VALIDATION_ERROR", "Момент выпуска должен быть на границе часа.")
        for turbine in context.turbines:
            expected = TURBINES[turbine.id]
            if abs(turbine.latitude - expected["latitude"]) > 1e-6 or abs(turbine.longitude - expected["longitude"]) > 1e-6:
                raise AppError(409, "CONFIGURATION_REQUIRED", "Координаты изменились: нужны новые погодные данные и модель.")

        bundle = None
        model_dir = self.model_dir or (ROOT / "artifacts/gfs-model" if (ROOT / "artifacts/gfs-model/model.joblib").exists() else ROOT / "artifacts/ensemble")
        for filename in ("model.joblib", "validation_model.joblib"):
            path = model_dir / filename
            if not path.exists():
                continue
            candidate = joblib.load(path)
            if pd.Timestamp(candidate["metadata"]["training_data_available_until"]) <= as_of:
                bundle, model_path = candidate, path
                break
        if bundle is None:
            raise AppError(409, "MODEL_ERROR", "Нет модели, обученной только на данных до выбранного момента.")
        metadata = bundle["metadata"]
        assumptions = metadata["time_assumptions"]
        offset = as_of.to_pydatetime().astimezone(ZoneInfo(context.source_timezone)).utcoffset().total_seconds() / 3600
        meaning = "start" if context.timestamp_meaning == "interval_start" else "end"
        if offset != assumptions["utc_offset_hours"] or meaning != assumptions["timestamp_convention"]:
            raise AppError(409, "CONFIGURATION_REQUIRED", "Временные настройки отличаются от обучения; требуется переобучение.")
        source_hashes = []
        for source in metadata["data"]["sources"]:
            source_path = context.input_dir / source["file"]
            checksum = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if checksum != source["sha256"]:
                raise AppError(409, "DATA_QUALITY_ERROR", "Исходные CSV изменились после обучения модели.")
            source_hashes.append(checksum)
        warnings = []
        if not assumptions.get("confirmed_by_organizers"):
            warnings.append("Исследовательские настройки: UTC+5, начало интервала, выпуск 23:00; организаторы их ещё не подтвердили.")
        emit("validate", 0.10, "Проверены координаты, исходные файлы и граница обучающей истории.", "validate_inputs")

        if metadata["kind"] == "noaa_gfs_operational_forecast":
            return self._run_gfs(request, context, bundle, model_path, source_hashes, warnings, emit)
        warnings.append("Previous Runs: точное время публикации неизвестно; доступность оценена с запасом 12 часов.")

        horizon = 48 if metadata.get("feature_set") == "trajectory" else request.horizon_hours
        first, last = as_of + pd.Timedelta(hours=1), as_of + pd.Timedelta(hours=horizon)
        months = list(pd.period_range(first.strftime("%Y-%m"), last.strftime("%Y-%m"), freq="M").astype(str))
        for month in months:
            for model in MODELS:
                destination = self.cache / model
                destination.mkdir(parents=True, exist_ok=True)
                for suffix in (".json", ".meta.json"):
                    name = month + suffix
                    if not (destination / name).exists() and (CACHE / model / name).exists():
                        shutil.copy2(CACHE / model / name, destination / name)
                try:
                    fetch_month(model, month, cache=self.cache, refresh=request.refresh_weather)
                except (httpx.HTTPError, OSError):
                    if not (destination / (month + ".meta.json")).exists():
                        raise AppError(503, "WEATHER_UNAVAILABLE", "Погодный архив недоступен и сохранённой копии нет.", retryable=True) from None
                    warning = f"Источник {model} временно недоступен; используется сохранённый архив {month}."
                    warnings.append(warning)
                    emit("weather", 0.20, warning, "fetch_weather", level="warning")
                if context.cancelled():
                    raise AppError(503, "JOB_INTERRUPTED", "Расчёт остановлен.")
        archive, manifests = load_archive(self.cache)
        try:
            weather = select_as_of(archive, as_of, horizon)
        except ValueError as error:
            raise AppError(503, "WEATHER_UNAVAILABLE", "Нет полного допустимого погодного прогноза для выбранного момента.", retryable=True) from error
        relevant = [row for row in manifests if Path(row["file"]).stem in months]
        weather_records = json.loads(weather.to_json(orient="records", date_format="iso", double_precision=15))
        weather_hash = digest(weather_records)
        model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
        inputs = digest({"weather": weather_hash, "weather_archives": [row["sha256"] for row in relevant], "model": model_hash, "source_hashes": source_hashes,
                         "as_of": as_of.isoformat(), "horizon": request.horizon_hours,
                         "turbines": request.turbine_ids, "assumptions": assumptions, "controller": "policy-v3"})
        emit("weather", 0.35, f"Выбраны {len(weather)} архивных погодных точек с допустимой границей доступности.", "select_as_of")
        emit("prepare", 0.45, "Подготовлена почасовая погода; будущая телеметрия не используется.", "prepare_features")
        emit("model", 0.55, f"Загружена модель {metadata['winner']}, версия {model_hash[:12]}.", "load_model")
        if context.previous is not None and context.previous_input_sha256 == inputs:
            previous = context.previous
            emit("predict", 0.75, "Входы не изменились; повторно используется предыдущий расчёт.", "reuse_forecast")
            return AgentResult(input_sha256=inputs, agent_mode="policy", model_name=metadata["winner"],
                model_version=previous.model_version,
                training_data_available_until=previous.training_data_available_until,
                series=[ComputedSeries(**series.model_dump(exclude={"storage_run_id"})) for series in previous.series],
                analysis=previous.analysis)
        with threadpool_limits(limits=2):
            weather["predicted_power"] = predict_weather(bundle, weather)
        selected = weather.loc[weather.lead_hour.le(request.horizon_hours) & weather.turbine_id.isin(request.turbine_ids)].copy()
        emit("predict", 0.78, f"Рассчитаны {len(selected)} почасовых значений на CPU.", "predict_weather")
        if not np.isfinite(selected.predicted_power).all() or not selected.predicted_power.between(0, 1).all():
            raise AppError(500, "DATA_QUALITY_ERROR", "Модель вернула некорректную мощность.")
        spread = (selected.gfs_global_wind_speed_100m - selected.icon_global_wind_speed_100m).abs()
        if spread.max() > 4:
            warnings.append(f"Расхождение GFS/ICON по ветру достигает {spread.max():.1f} м/с; прогноз требует внимания.")
        ramps = selected.groupby("turbine_id").predicted_power.diff().abs()
        if ramps.max() > 0.3:
            warnings.append(f"Прогнозируется изменение мощности до {ramps.max():.2f} за час.")
        series = []
        sources_by_key = {(row["model"], Path(row["file"]).stem): PreviousRunsWeatherSource(
            source_id=row["model"] + ":" + Path(row["file"]).stem,
            provider="Open-Meteo", model=row["model"], sha256=row["sha256"], retrieved_at=row["retrieved_at"],
        ) for row in relevant}
        for turbine, group in selected.groupby("turbine_id"):
            used_months = set(group.valid_time.dt.strftime("%Y-%m"))
            series.append(ComputedSeries(turbine_id=int(turbine), points=[ForecastPoint(
                valid_time=row.valid_time.to_pydatetime(), lead_hour=int(row.lead_hour),
                predicted_power=float(row.predicted_power),
                **point_weather(row, tuple(f"{model}_" for model in MODELS)), weather_inputs=[WeatherInput(
                    source_id=sources_by_key[model, row.valid_time.strftime("%Y-%m")].source_id,
                    forecast_offset_days=int(row.forecast_offset_days),
                    available_at_estimate=row.available_at_upper_bound.to_pydatetime(),
                ) for model in MODELS],
            ) for row in group.itertuples()], weather=WeatherProvenance(
                sources=[source for (model, month), source in sources_by_key.items() if month in used_months],
            )))
        changed = " Входные данные изменились, создан новый расчёт." if context.previous else ""
        summary = (f"Прогноз на {request.horizon_hours} ч для {len(series)} турбин: "
                   f"мощность {selected.predicted_power.min():.3f}–{selected.predicted_power.max():.3f}." + changed)
        emit("review", 0.92, summary, "review_forecast")
        return AgentResult(input_sha256=inputs, agent_mode="policy", model_name=metadata["winner"],
            model_version=model_hash, training_data_available_until=metadata["training_data_available_until"],
            series=series, analysis=ForecastAnalysis(summary=summary, warnings=warnings))

    def _run_gfs(self, request, context, bundle, model_path, source_hashes, warnings, emit):
        from concurrent.futures import ThreadPoolExecutor

        from scripts.fetch_gfs_runs import fetch_day
        from src.gfs_model import predict
        from src.gfs_weather import CACHE as GFS_CACHE
        from src.gfs_weather import select_run

        as_of = pd.Timestamp(request.as_of)
        if as_of.hour != 18:
            raise AppError(422, "VALIDATION_ERROR", "Текущий архив NOAA рассчитан на ежедневный выпуск в 18:00 UTC.")
        day = as_of.strftime("%Y-%m-%d")
        cache = Path(os.environ.get("RENTBOX_GFS_CACHE", ROOT / "data/gfs-runtime"))
        cache.mkdir(parents=True, exist_ok=True)
        for suffix in (".csv", ".meta.json"):
            source_path = GFS_CACHE / (day + suffix)
            destination = cache / (day + suffix)
            if not destination.exists() and source_path.exists():
                shutil.copy2(source_path, destination)
        if not (cache / (day + ".csv")).exists() or request.refresh_weather:
            try:
                cache.mkdir(parents=True, exist_ok=True)
                with httpx.Client(timeout=8, limits=httpx.Limits(max_connections=8)) as client, ThreadPoolExecutor(max_workers=4) as pool:
                    fetch_day(as_of.tz_convert("UTC").tz_localize(None).normalize(), cache, "0p25", pool, client,
                              refresh=request.refresh_weather)
            except (httpx.HTTPError, OSError, ImportError) as error:
                if not (cache / (day + ".csv")).exists():
                    raise AppError(503, "WEATHER_UNAVAILABLE", "Не удалось получить операционный архив NOAA GFS.", retryable=True) from error
                warnings.append("Источник NOAA недоступен; используется сохранённый проверенный архив.")
        try:
            weather, manifest = select_run(as_of, cache)
        except (ValueError, OSError) as error:
            raise AppError(503, "WEATHER_UNAVAILABLE", "Нет полного выпуска NOAA с доказанной доступностью на момент решения.") from error
        emit("weather", 0.35, "Проверены цикл GFS и время размещения всех исходных файлов: не позже as_of.", "noaa_archive")
        emit("prepare", 0.45, "Подготовлены почасовые значения из прогнозных опор одного цикла; наблюдения не используются.", "gfs_features")
        model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
        inputs = digest({"weather": manifest["sha256"], "model": model_hash, "sources": source_hashes,
            "as_of": as_of.isoformat(), "horizon": request.horizon_hours, "turbines": request.turbine_ids,
            "assumptions": bundle["metadata"]["time_assumptions"], "controller": "noaa-policy-v2"})
        emit("model", 0.55, f"Загружена модель NOAA GFS, версия {model_hash[:12]}.", "load_model")
        if context.previous is not None and context.previous_input_sha256 == inputs:
            emit("predict", 0.8, "Погода и модель не изменились: используется сохранённый расчёт.", "reuse_forecast")
            previous = context.previous
            return AgentResult(input_sha256=inputs, agent_mode="policy", model_name=bundle["metadata"]["winner"],
                model_version=previous.model_version, training_data_available_until=previous.training_data_available_until,
                series=[ComputedSeries(**s.model_dump(exclude={"storage_run_id"})) for s in previous.series], analysis=previous.analysis)
        with threadpool_limits(limits=2):
            weather["predicted_power"] = predict(bundle, weather)
        selected = weather.loc[weather.lead_hour.le(request.horizon_hours) & weather.turbine_id.isin(request.turbine_ids)]
        emit("predict", 0.78, f"Рассчитаны {len(selected)} почасовых значений по NOAA GFS на CPU.", "gfs_predict")
        ramp = selected.groupby("turbine_id").predicted_power.diff().abs().max()
        if ramp > 0.3:
            warnings.append(f"В прогнозе есть изменение мощности до {ramp:.2f} за час.")
        source = SingleRunWeatherSource(source_id="gfs:" + manifest["sha256"][:16], provider="NOAA GFS",
            model="gfs_0p25", initialization_time=manifest["initialization_time"], available_at=manifest["available_at"],
            availability_basis=manifest["availability_basis"] + f"; data/gfs-runs/{day}.meta.json",
            retrieved_at=manifest["retrieved_at"], sha256=manifest["sha256"])
        series = [ComputedSeries(turbine_id=int(turbine), weather=WeatherProvenance(sources=[source]),
            points=[ForecastPoint(valid_time=row.valid_time.to_pydatetime(), lead_hour=int(row.lead_hour),
                predicted_power=float(row.predicted_power), **point_weather(row),
                weather_inputs=[WeatherInput(source_id=source.source_id)]) for row in group.itertuples()]) for turbine, group in selected.groupby("turbine_id")]
        summary = f"Прогноз NOAA GFS на {request.horizon_hours} ч: {len(series)} турбины, мощность {selected.predicted_power.min():.3f}–{selected.predicted_power.max():.3f}."
        emit("review", 0.92, summary, "review_forecast")
        return AgentResult(input_sha256=inputs, agent_mode="policy", model_name=bundle["metadata"]["winner"],
            model_version=model_hash, training_data_available_until=bundle["metadata"]["training_data_available_until"],
            series=series, analysis=ForecastAnalysis(summary=summary, warnings=warnings))


def create_agent() -> ForecastAgent:
    return ForecastAgent()
