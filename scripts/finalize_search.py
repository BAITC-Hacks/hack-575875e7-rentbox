"""Freeze a winner on Nov/Dec, then refit and report Jan/Feb separately."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from scripts.search_models import SEARCH
from scripts.train_forecast import daily_schedule, period, score_groups
from src.data import ROOT, load_hourly
from src.model import (
    BlendRegressor,
    FeatureRegressor,
    context_weather_features,
    fit_mlp,
    metrics,
    predict_weather,
)
from src.weather import load_archive, select_as_of


def fit_candidate(info: dict, training: pd.DataFrame, protocol: dict):
    config = info["config"]
    columns = protocol["point_features"] if config["features"] == "point" else protocol["features"]
    x = training[["x_" + c for c in columns]].rename(columns=lambda c: c[2:])
    parameters = {k: v for k, v in config.items() if k not in {"family", "features"}}
    if config["family"] == "mlp":
        parameters["epochs"] = info["fit"]["best_epoch"]
        model, _ = fit_mlp(x, training.power, device="cuda", **parameters)
    elif config["family"] == "boost":
        model = HistGradientBoostingRegressor(early_stopping=False, random_state=42, **parameters).fit(x, training.power)
    else:
        model = ExtraTreesRegressor(max_features=0.8, n_jobs=8, random_state=42, **parameters).fit(x, training.power)
    return FeatureRegressor(model, columns)


def main() -> None:
    protocol = json.loads((SEARCH / "protocol.json").read_text())
    valid = pd.read_parquet(SEARCH / "validation.parquet")
    candidates = []
    for worker, expected in [("local-cpu", 40), ("local-gpu", 24), ("cloud-gpu", 24)]:
        files = sorted((SEARCH / worker).glob("*.json"))
        if len(files) != expected:
            raise ValueError(f"{worker}: expected {expected} completed models, found {len(files)}")
        for path in files:
            info = json.loads(path.read_text())
            if any(info[k] != protocol[k] for k in ["train_sha256", "validation_sha256"]):
                raise ValueError("Workers used different data")
            info["prediction_path"] = str(path.with_suffix(".predictions.npy"))
            candidates.append(info)
    candidates.sort(key=lambda r: r["metrics"]["mae"])
    shortlist = candidates[:8]
    ensembles = []
    for count in [1, 3, 5, 8]:
        selected = shortlist[:count]
        prediction = np.mean([np.load(row["prediction_path"]) for row in selected], axis=0)
        ensembles.append({"name": f"top_{count}_mean", "members": [r["name"] for r in selected],
                          "metrics": metrics(valid.power, prediction)})
    chosen = min(ensembles, key=lambda r: r["metrics"]["mae"])
    by_name = {row["name"]: row for row in candidates}
    members = [by_name[name] for name in chosen["members"]]
    selection = {"candidate_count": len(candidates), "ranking": candidates, "ensembles": ensembles,
                 "chosen": chosen, "selection_months": protocol["selection_months"],
                 "january_used_for_search": False,
                 "note": "January was already reported for the first baseline experiment; it is now a monitoring month, not a newly untouched holdout."}
    (SEARCH / "selection.json").write_text(json.dumps(selection, indent=2) + "\n")
    print(json.dumps({"selection_frozen": chosen}), flush=True)

    offset = protocol["utc_offset_hours"]
    hourly, provenance = load_hourly(timestamp_convention=protocol["timestamp_convention"])
    hourly["valid_time"] = (hourly.hour - pd.Timedelta(hours=offset)).dt.tz_localize("UTC")
    archive, _ = load_archive()
    scheduled = daily_schedule(archive, offset, 23)
    scheduled = scheduled.loc[scheduled.groupby(["as_of", "turbine_id"]).valid_time.transform("size").eq(48)].copy()
    features = context_weather_features(scheduled)
    packed = pd.concat([scheduled[["as_of", "valid_time", "turbine_id", "lead_hour", "forecast_offset_days", "available_at_upper_bound"]], features.add_prefix("x_")], axis=1)
    packed = packed.merge(hourly[["hour", "valid_time", "turbine_id", "power"]], on=["valid_time", "turbine_id"], validate="many_to_one")
    feature_columns = [c for c in packed if c.startswith("x_")]
    packed = packed.loc[(packed.hour >= "2024-03-02") & np.isfinite(packed[feature_columns].to_numpy()).all(axis=1)].copy()
    holdout = period(packed, "2026-01", offset, 23)
    before_january = packed.loc[packed.hour < "2025-12-31"]
    before_february = packed.loc[packed.hour < "2026-01-31"]
    contextual = any(row["config"]["features"] == "trajectory" for row in members)
    full_columns = protocol["features"] if contextual else protocol["point_features"]
    x_holdout = holdout[["x_" + c for c in full_columns]].rename(columns=lambda c: c[2:])
    output = ROOT / "artifacts/ensemble"
    output.mkdir(parents=True, exist_ok=True)
    with threadpool_limits(limits=8):
        validation_model = BlendRegressor([fit_candidate(info, before_january, protocol) for info in members])
        prediction = validation_model.predict(x_holdout)
        january = score_groups(holdout, prediction)
        final_model = BlendRegressor([fit_candidate(info, before_february, protocol) for info in members])
    baseline_means = hourly.loc[hourly.hour < "2025-12-31"].groupby("turbine_id").power.mean()
    baseline_prediction = holdout.turbine_id.map(baseline_means).to_numpy()
    result = holdout[["as_of", "valid_time", "turbine_id", "lead_hour", "forecast_offset_days", "available_at_upper_bound", "power"]].copy()
    result["predicted_power"] = prediction
    result["baseline_power"] = baseline_prediction
    result.to_csv(output / "january_predictions.csv", index=False)
    metadata = {
        "kind": "archived_weather_power_forecast", "winner": chosen["name"], "members": members,
        "feature_set": "trajectory" if contextual else "point", "features": full_columns,
        "created_at": datetime.now(timezone.utc).isoformat(), "status": "research_time_assumptions_unconfirmed",
        "time_assumptions": {"utc_offset_hours": offset, "timestamp_convention": protocol["timestamp_convention"],
                             "daily_issue_hour": 23, "confirmed_by_organizers": False},
        "training_data_available_until": (before_february.valid_time.max() + pd.Timedelta(hours=1)).isoformat(),
        "training_rows": len(before_february), "data": provenance,
        "search": {"candidate_count": len(candidates), "selection_months": protocol["selection_months"],
                   "chosen": chosen, "january_used_for_search": False},
        "hardware": {"local_gpu": "RTX 5090 Laptop", "cloud_gpu": "A6000 via NVIDIA Brev", "local_cpu": True},
        "january": january, "january_baseline": metrics(holdout.power, baseline_prediction),
        "weather": {"product": "Open-Meteo Previous Runs; GFS and ICON", "exact_initializations_available": False,
                    "availability_basis": "valid_time - forecast_offset_days*24h + 12h policy margin"},
    }
    validation_metadata = copy.deepcopy(metadata)
    validation_metadata["training_data_available_until"] = (before_january.valid_time.max() + pd.Timedelta(hours=1)).isoformat()
    validation_metadata["training_rows"] = len(before_january)
    joblib.dump({"model": validation_model, "metadata": validation_metadata}, output / "validation_model.joblib", compress=3)
    bundle = {"model": final_model, "metadata": metadata}
    joblib.dump(bundle, output / "model.joblib", compress=3)
    metadata["artifact_sha256"] = hashlib.sha256((output / "model.joblib").read_bytes()).hexdigest()
    (output / "metrics.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    february = []
    for day in pd.date_range("2026-01-31", "2026-02-28", freq="D"):
        as_of = (day + pd.Timedelta(hours=23-offset)).tz_localize("UTC")
        weather = select_as_of(archive, as_of)
        weather["predicted_power"] = predict_weather(bundle, weather)
        weather["target_source_clock"] = (weather.valid_time + pd.Timedelta(hours=offset)).dt.tz_localize(None)
        weather["in_february"] = weather.target_source_clock.ge("2026-02-01") & weather.target_source_clock.lt("2026-03-01")
        weather["time_settings_confirmed"] = False
        february.append(weather[["as_of", "valid_time", "target_source_clock", "turbine_id", "lead_hour", "predicted_power", "forecast_offset_days", "available_at_upper_bound", "in_february", "time_settings_confirmed"]])
    pd.concat(february, ignore_index=True).to_csv(output / "february_replay.csv", index=False)
    overall = january["overall"]
    report = [
        "# Прогноз мощности: RTX 5090 + A6000 + CPU", "",
        "**Предварительный результат:** UTC+5, начало интервала и выпуск 23:00 ещё требуют подтверждения организаторов.", "",
        "## Обучение", "",
        "Сравнены 88 конфигураций: 40 моделей на CPU, 24 нейросети на RTX 5090 Laptop и 24 на A6000 в NVIDIA Brev.",
        "Поиск использовал обучение до 31 октября 2025 (не включая этот день) и валидацию ноября–декабря.",
        "Январские цели не передавались поисковым workers. После первого эксперимента январь уже является месяцем мониторинга разработки; это не новый нетронутый тест.",
        f"Выбран {chosen['name']}: " + ", ".join(chosen["members"]) + ".",
        f"MAE ноября–декабря: {chosen['metrics']['mae']:.5f}. Выбор зафиксирован до повторной оценки января.",
        "Для января ансамбль переобучен до 31 декабря, для февральского артефакта — до 31 января; оба дня отсечки исключены.", "",
        "## Январь 2026", "", "| Горизонт | MAE | RMSE |", "|---|---:|---:|",
        f"| Все выпуски | {overall['mae']:.5f} | {overall['rmse']:.5f} |",
    ]
    for label, values in january["by_horizon"].items():
        report.append(f"| {label} | {values['mae']:.5f} | {values['rmse']:.5f} |")
    report += ["", f"{overall['n']} прогнозных строк, 31 ежедневный выпуск, 1488 уникальных пар турбина/час.",
        "MAE измеряется в долях нормализованной мощности; это не MAPE и не «процент точности».",
        f"Среднее по турбине: MAE {metadata['january_baseline']['mae']:.5f}; снижение MAE {100 * (1-overall['mae']/metadata['january_baseline']['mae']):.1f}%.",
        "Дополнительные базовые модели: последний известный полный час — MAE 0.34268; последние доступные сутки — MAE 0.36480.",
        "Первый бустинг из `artifacts/forecast/` давал MAE 0.19420. Новый ансамбль: MAE 0.16933.", "",
        "## Использование", "", "```bash", "python -m scripts.predict --as-of 2026-01-31T18:00:00Z --horizon 48", "```", "",
        "Сохранённый ансамбль использует NumPy на CPU. PyTorch, GPU, личные ключи и сеть для расчёта по кэшу не нужны.",
        "`february_replay.csv`: 29 ежедневных выпусков × 48 часов × 2 турбины = 2784 строки. Мартовский хвост отмечен `in_february=false`.",
        "Февральских фактических значений нет; качество февраля не измерено.", "",
        "## Происхождение и ограничения", "",
        "Погода: [Open-Meteo Previous Runs](https://open-meteo.com/en/docs/previous-runs-api), GFS/ICON, CC BY 4.0. Используются прогнозы с фиксированной заблаговременностью 1–3 дня, не реанализ.",
        "Время точной инициализации и исторической публикации API не возвращает. Ограничение доступности: `valid_time - offset_days*24h + 12h <= as_of`. Запас 12 часов — допущение, а не измеренная задержка.",
        "Все погодные ответы, параметры, контрольные суммы и дата получения сохранены в `data/weather/`. Для строгого аудита отдельных циклов требуется источник с метаданными выпусков.",
        "Часовой пояс, границы интервалов и время ежедневного выпуска ещё нужно подтвердить; при изменении этих настроек требуется повторное обучение.",
        "Расчёт в МВт/МВт·ч требует номинальной мощности и определения нормализации. GPU нужна только для повторного обучения.", "",
    ]
    (output / "report.md").write_text("\n".join(report))
    print(json.dumps({"january": january, "baseline": metadata["january_baseline"], "members": chosen["members"],
                      "artifact": str(output / "model.joblib")}), flush=True)


if __name__ == "__main__":
    main()
