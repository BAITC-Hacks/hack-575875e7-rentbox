"""Compare real archived-weather regressors on chronological splits.

Time settings are explicit research assumptions until confirmed by organizers.
python -m scripts.train_forecast --utc-offset 5 --timestamp-convention start --device cuda
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from src.data import ROOT, load_hourly
from src.model import (
    BlendRegressor,
    FeatureRegressor,
    TurbinePowerCurve,
    fit_mlp,
    metrics,
    predict_weather,
    weather_features,
)
from src.weather import PUBLICATION_MARGIN_HOURS, load_archive, select_as_of


def daily_schedule(archive: pd.DataFrame, offset: int, issue_hour: int) -> pd.DataFrame:
    """Vectorized daily 48-hour replay using only offset products allowed as-of."""
    local_hour = (archive.valid_time + pd.Timedelta(hours=offset)).dt.hour
    first_lead = (local_hour - issue_hour - 1) % 24 + 1
    tables = []
    for day in (0, 1):
        lead = first_lead + day * 24
        needed_offset = np.ceil((lead + PUBLICATION_MARGIN_HOURS) / 24).astype(int)
        frame = archive.loc[archive.forecast_offset_days == needed_offset].copy()
        frame["lead_hour"] = lead.loc[frame.index]
        frame["as_of"] = frame.valid_time - pd.to_timedelta(frame.lead_hour, unit="h")
        if (frame.available_at_upper_bound > frame.as_of).any():
            raise ValueError("Weather availability violation")
        tables.append(frame)
    return pd.concat(tables, ignore_index=True).sort_values(["as_of", "turbine_id", "valid_time"]).reset_index(drop=True)


def period(frame: pd.DataFrame, month: str, offset: int, issue_hour: int) -> pd.DataFrame:
    p = pd.Period(month, freq="M")
    first_issue_local = p.start_time - pd.Timedelta(days=1) + pd.Timedelta(hours=issue_hour)
    first_issue_utc = (first_issue_local - pd.Timedelta(hours=offset)).tz_localize("UTC")
    return frame.loc[(frame.hour >= p.start_time) & (frame.hour < p.end_time + pd.Timedelta(nanoseconds=1))
                     & (frame.as_of >= first_issue_utc)].copy()


def build_candidates(columns: list[str]) -> dict:
    candidates = {}
    for provider in ["gfs_global", "icon_global"]:
        wind_column = provider + "_wind_speed_100m"
        candidates[f"curve_{provider}"] = FeatureRegressor(
            TurbinePowerCurve(wind_column), ["turbine_id", wind_column]
        )
        subset = [c for c in columns if c.startswith(provider) or not c.startswith(("gfs_", "icon_", "models_"))]
        candidates[f"boost_{provider}"] = FeatureRegressor(HistGradientBoostingRegressor(
            max_iter=250, max_leaf_nodes=15, min_samples_leaf=80,
            l2_regularization=20, learning_rate=0.05, early_stopping=False, random_state=42,
        ), subset)
    for loss in ["squared_error", "absolute_error"]:
        candidates[f"boost_both_{loss}"] = FeatureRegressor(HistGradientBoostingRegressor(
            loss=loss, max_iter=300, max_leaf_nodes=15, min_samples_leaf=80,
            l2_regularization=20, learning_rate=0.05, early_stopping=False, random_state=42,
        ), columns)
    candidates["extra_trees_both"] = FeatureRegressor(ExtraTreesRegressor(
        n_estimators=200, max_depth=18, min_samples_leaf=24, max_features=0.8,
        n_jobs=8, random_state=42,
    ), columns)
    return candidates


def fit_selected(name: str, blueprints: dict, frame: pd.DataFrame, device: str, epochs: int):
    features = weather_features(frame)
    if name == "neural_both":
        return fit_mlp(features, frame.power, device=device, epochs=epochs)[0]
    if name == "blend_boost_neural":
        return BlendRegressor([
            fit_selected("boost_both_squared_error", blueprints, frame, device, epochs),
            fit_selected("neural_both", blueprints, frame, device, epochs),
        ])
    return copy.deepcopy(blueprints[name]).fit(features, frame.power)


def score_groups(frame: pd.DataFrame, prediction: np.ndarray) -> dict:
    results = {"overall": metrics(frame.power, prediction), "by_turbine": {}, "by_horizon": {}}
    for t in [1, 2]:
        mask = frame.turbine_id.to_numpy() == t
        results["by_turbine"][str(t)] = metrics(frame.loc[mask, "power"], prediction[mask])
    for label, mask in [("1-24h", frame.lead_hour.to_numpy() <= 24), ("25-48h", frame.lead_hour.to_numpy() > 24)]:
        results["by_horizon"][label] = metrics(frame.loc[mask, "power"], prediction[mask])
    results["unique_target_hours"] = len(frame.drop_duplicates(["valid_time", "turbine_id"]))
    results["daily_issues"] = frame.as_of.nunique()
    return results


def markdown_report(meta: dict) -> str:
    ranking = sorted(meta["candidates"], key=lambda row: row["december"]["mae"])
    lines = ["# Обучение прогноза мощности ВЭС", "",
        "**Исследовательский результат:** временные настройки ещё не подтверждены организаторами.", "",
        f"- Гипотеза: время CSV = UTC{meta['time_assumptions']['utc_offset_hours']:+d}, метка 10 минут — `{meta['time_assumptions']['timestamp_convention']}`.",
        f"- Ежедневный выпуск: {meta['time_assumptions']['daily_issue_hour']:02d}:00 по часам CSV; горизонт 48 часов.",
        "- Только полные часы из шести измерений; пропуски мощности не заполняются.",
        "- Обучение: март 2024 — ноябрь 2025, без последних суток ноября.",
        "- Выбор модели: декабрь 2025. После выбора — переобучение до 31 декабря (не включая этот день), затем проверка января.",
        "- Финальный артефакт переобучен до 31 января (не включая этот день); данных февраля в обучении нет.",
        "- Признаки: архивные прогнозы GFS и ICON, календарь, номер турбины. Фактической будущей погоды и будущей мощности среди признаков нет.", "",
        "## Выбор по декабрю", "", "| Модель | MAE | RMSE |", "|---|---:|---:|"]
    for row in ranking:
        lines.append(f"| {row['model']} | {row['december']['mae']:.5f} | {row['december']['rmse']:.5f} |")
    overall = meta["january"]["overall"]
    lines += ["", "## Январь: проверка выбранной модели", "", f"Выбрана **{meta['winner']}** до просмотра январских результатов.", "",
              f"MAE **{overall['mae']:.5f}**, RMSE **{overall['rmse']:.5f}**, bias **{overall['bias']:.5f}**.",
              "Ошибки в долях нормализованной мощности; MAE × 100 — процентные пункты шкалы, не MAPE.", "",
              "| Срез | Число прогнозов | MAE | RMSE |", "|---|---:|---:|---:|"]
    for group in ["by_turbine", "by_horizon"]:
        for name, values in meta["january"][group].items():
            label = "Турбина " + name if group == "by_turbine" else name
            lines.append(f"| {label} | {values['n']} | {values['mae']:.5f} | {values['rmse']:.5f} |")
    base = meta["january_baseline"]
    lines += ["", f"Базовый прогноз средним по турбине: MAE {base['mae']:.5f}. Улучшение MAE: {100 * (1-overall['mae']/base['mae']):.1f}%.",
              f"Оценены {meta['january']['daily_issues']} ежедневный выпуск, {meta['january']['unique_target_hours']} уникальных пар турбина/час. Повторные прогнозы одного часа оцениваются отдельно.", "",
              "## Происхождение и доступность погоды", "",
              "[Open-Meteo Previous Runs](https://open-meteo.com/en/docs/previous-runs-api) хранит прогнозы с фиксированной заблаговременностью 1–3 дня.",
              "Это набор прогнозных значений из разных циклов, а не один выпуск. Номер и точное время публикации каждого исходного цикла API не возвращает.",
              "Применяется явная политика: `available_at_upper_bound = valid_time - offset_days * 24h + 12h`. Для каждого часа выбирается самый свежий разрешённый offset, граница обязана быть не позже `as_of`.",
              "Запас 12 ч учитывает вычисление, поступление и округление циклов; это допущение, не измеренная историческая задержка. Для строгого аудита каждого цикла нужен архив с полными метаданными выпусков.",
              "Ответы API, параметры, SHA-256 и реальное время получения сохраняются в `data/weather/`. Повторный запуск обучения работает без сети.", "",
              "## Ограничения", "",
              "- Часовой пояс и семантика меток требуют подтверждения; при другом ответе модели нужно переобучить.",
              "- Месяц проверки один; одинаковые часы в соседних выпусках статистически зависимы.",
              "- Факта февраля нет: CSV с февральскими прогнозами не является оценкой качества.",
              "- Выход — нормализованная мощность каждой турбины 0–1; пересчёта в МВт/МВт·ч нет.",
              "- Остановки, ограничения сети и ремонты без дополнительных признаков могут быть непредсказуемы.",
              "- Отдельный опыт `artifacts/power_curve/` использует фактическую погоду и не сравним с этими прогнозными метриками.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--utc-offset", type=int, required=True, choices=range(-12, 15))
    parser.add_argument("--timestamp-convention", required=True, choices=["start", "end"])
    parser.add_argument("--issue-hour", type=int, default=23, choices=range(24))
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cpu")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/forecast")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    hourly, provenance = load_hourly(timestamp_convention=args.timestamp_convention)
    archive, manifests = load_archive()
    hourly["valid_time"] = (hourly.hour - pd.Timedelta(hours=args.utc_offset)).dt.tz_localize("UTC")
    hourly["actual_available_at"] = hourly.valid_time + pd.Timedelta(hours=1)
    scheduled = daily_schedule(archive, args.utc_offset, args.issue_hour)
    joined = scheduled.merge(hourly[["hour", "valid_time", "turbine_id", "power", "actual_available_at"]],
                             on=["valid_time", "turbine_id"], validate="many_to_one", how="inner")
    finite = np.isfinite(weather_features(joined).to_numpy()).all(axis=1)
    joined = joined.loc[finite & (joined.hour >= "2024-03-02")].copy()
    train = joined.loc[joined.hour < "2025-11-30"].copy()
    selection = period(joined, "2025-12", args.utc_offset, args.issue_hour)
    holdout = period(joined, "2026-01", args.utc_offset, args.issue_hour)
    if train.actual_available_at.max() > selection.as_of.min():
        raise ValueError("Training targets unavailable at the first validation issue")
    print(json.dumps({"train_rows": len(train), "selection_rows": len(selection), "holdout_rows": len(holdout),
                      "research_utc_offset": args.utc_offset, "timestamp_convention": args.timestamp_convention}), flush=True)
    x_train, x_selection = weather_features(train), weather_features(selection)
    blueprints = build_candidates(list(x_train.columns))
    candidates, comparison = {}, []
    with threadpool_limits(limits=8):
        for name, blueprint in blueprints.items():
            started = time.monotonic()
            model = copy.deepcopy(blueprint).fit(x_train, train.power)
            candidates[name] = model
            row = {"model": name, "december": metrics(selection.power, model.predict(x_selection)),
                   "seconds": round(time.monotonic() - started, 2)}
            comparison.append(row)
            print(json.dumps(row), flush=True)
        neural, gpu = fit_mlp(x_train, train.power, x_selection, selection.power, device=args.device)
        candidates["neural_both"] = neural
        candidates["blend_boost_neural"] = BlendRegressor([candidates["boost_both_squared_error"], neural])
        for name in ["neural_both", "blend_boost_neural"]:
            row = {"model": name, "december": metrics(selection.power, candidates[name].predict(x_selection))}
            comparison.append(row)
            print(json.dumps(row), flush=True)
        winner = min(comparison, key=lambda row: row["december"]["mae"])["model"]
        print(f"Selection frozen: {winner}. Evaluating January now.", flush=True)
        pre_january = joined.loc[joined.hour < "2025-12-31"]
        if pre_january.actual_available_at.max() > holdout.as_of.min():
            raise ValueError("Training targets unavailable at first January issue")
        chosen = fit_selected(winner, blueprints, pre_january, args.device, gpu["best_epoch"])
        prediction = np.clip(chosen.predict(weather_features(holdout)), 0, 1)
        january = score_groups(holdout, prediction)
        # Baseline mean uses each physical hour once, not duplicate daily forecasts.
        base_train = hourly.loc[hourly.hour < "2025-12-31"]
        base_means = base_train.groupby("turbine_id").power.mean()
        baseline = holdout.turbine_id.map(base_means).to_numpy()
        columns = ["as_of", "valid_time", "hour", "turbine_id", "lead_hour", "forecast_offset_days", "available_at_upper_bound", "power"]
        validation_output = holdout[columns].copy()
        validation_output["predicted_power"] = prediction
        validation_output["baseline_power"] = baseline
        validation_output.to_csv(args.output / "january_predictions.csv", index=False)
        # A separate frozen validation artifact can replay January without future targets.
        final = joined.loc[joined.hour < "2026-01-31"]
        final_model = fit_selected(winner, blueprints, final, args.device, gpu["best_epoch"])
        metadata = {
            "kind": "archived_weather_power_forecast", "winner": winner,
            "created_at": datetime.now(timezone.utc).isoformat(), "status": "research_time_assumptions_unconfirmed",
            "time_assumptions": {"utc_offset_hours": args.utc_offset, "timestamp_convention": args.timestamp_convention,
                                 "daily_issue_hour": args.issue_hour, "confirmed_by_organizers": False},
            "data": provenance, "weather_manifest": manifests,
            "weather": {"provider": "Open-Meteo", "models": ["gfs_global", "icon_global"],
                        "product": "previous_runs_fixed_offsets", "offset_days": [1, 2, 3],
                        "publication_margin_hours": PUBLICATION_MARGIN_HOURS, "exact_initializations_available": False},
            "split": {"train_start": "2024-03-02", "train_before": "2025-11-30", "model_selection": "2025-12",
                      "validation_refit_before": "2025-12-31", "untouched_holdout": "2026-01", "final_refit_before": "2026-01-31"},
            "training_data_available_until": final.actual_available_at.max().isoformat(),
            "training_rows": len(final), "training_unique_hours": len(final.drop_duplicates(["valid_time", "turbine_id"])),
            "features": list(x_train.columns), "selection_metric": "MAE; December only", "candidates": comparison,
            "gpu_training": gpu, "january": january, "january_baseline": metrics(holdout.power, baseline),
            "versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__},
        }
        validation_metadata = copy.deepcopy(metadata)
        validation_metadata["training_data_available_until"] = pre_january.actual_available_at.max().isoformat()
        validation_metadata["training_rows"] = len(pre_january)
        validation_metadata["training_unique_hours"] = len(pre_january.drop_duplicates(["valid_time", "turbine_id"]))
        validation_metadata["artifact_purpose"] = "January evaluation; no January training targets"
        joblib.dump({"model": chosen, "metadata": validation_metadata}, args.output / "validation_model.joblib", compress=3)
        bundle = {"model": final_model, "metadata": metadata}
        model_path = args.output / "model.joblib"
        joblib.dump(bundle, model_path, compress=3)
        metadata["artifact_sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()
        (args.output / "metrics.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
        (args.output / "report.md").write_text(markdown_report(metadata))
        # Full replay from January 31 through February 28. March tail is retained and marked.
        february = []
        for local_day in pd.date_range("2026-01-31", "2026-02-28", freq="D"):
            as_of = (local_day + pd.Timedelta(hours=args.issue_hour - args.utc_offset)).tz_localize("UTC")
            weather = select_as_of(archive, as_of)
            weather["predicted_power"] = predict_weather(bundle, weather)
            weather["target_source_clock"] = (weather.valid_time + pd.Timedelta(hours=args.utc_offset)).dt.tz_localize(None)
            weather["in_february"] = weather.target_source_clock.ge("2026-02-01") & weather.target_source_clock.lt("2026-03-01")
            weather["model_name"] = winner
            weather["time_settings_confirmed"] = False
            february.append(weather[["as_of", "valid_time", "target_source_clock", "turbine_id", "lead_hour", "predicted_power",
                                     "forecast_offset_days", "available_at_upper_bound", "model_name", "in_february", "time_settings_confirmed"]])
        pd.concat(february, ignore_index=True).to_csv(args.output / "february_replay.csv", index=False)
        print(json.dumps({"winner": winner, "january": january, "baseline": metadata["january_baseline"],
                          "february_rows": sum(len(f) for f in february), "artifact": str(model_path)}), flush=True)


if __name__ == "__main__":
    main()
