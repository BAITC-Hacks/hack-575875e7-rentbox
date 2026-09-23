# API для фронта — проект контракта v0

**Статус:** контракт для параллельной разработки. Серверные маршруты ниже
ещё не реализованы; примеры показывают формат, а не готовые прогнозы.

Базовый путь: `/api`. При локальной разработке сервер планируется на порту 8000.
Фронт проксирует `/api` на сервер. Опрос статуса раз в 1–2 секунды достаточен
для первого рабочего сценария.

## Общие соглашения

- Даты API — ISO 8601 с обязательным смещением; ответы — UTC с `Z`.
- `as_of` — момент принятия решения: какие данные можно использовать.
- `valid_time` — метка прогнозного часа. Семантика границ часового интервала
  будет закреплена после уточнения десятиминутных меток исходных CSV.
- `lead_hour` — число часов от `as_of` до метки прогнозного часа, 1…24/48.
- `turbine_id` — целое число `1` или `2`, как в `src/storage.py` и названиях файлов.
- `predicted_power` — нормализованная мощность от 0 до 1.
- Неизвестные метрики и факты — `null`, а не искусственные нули.
- `agent_mode` — `llm` или `policy`: реальный режим управления инструментами.
- Примеры дат ниже иллюстрируют формат. Они не утверждают время ежедневного выпуска.

## Маршруты

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/health` | Готовность сервера |
| GET | `/turbines` | Номера, названия и координаты турбин |
| GET | `/data/summary` | Границы истории, качество, конфигурация времени |
| POST | `/agent/runs` | Запустить прогноз для одного момента решения |
| GET | `/agent/runs/{run_id}` | Статус, текущий шаг, события и ошибки |
| GET | `/agent/runs/{run_id}/forecast` | Почасовые результаты и происхождение |
| GET | `/agent/runs/{run_id}/forecast.csv` | Скачать тот же результат в CSV |
| POST | `/agent/replays` | Последовательность ежедневных прогнозов |
| GET | `/agent/replays/{replay_id}` | Прогресс последовательности и ID её запусков |

## Турбины

`GET /api/turbines`

```json
{
  "items": [
    {"id": 1, "name": "Турбина 1", "latitude": 43.645150, "longitude": 78.535604},
    {"id": 2, "name": "Турбина 2", "latitude": 43.643198, "longitude": 78.538828}
  ]
}
```

## Запуск

`POST /api/agent/runs`

```json
{
  "as_of": "2026-01-31T18:00:00Z",
  "horizon_hours": 48,
  "turbine_ids": [1, 2],
  "refresh_weather": false
}
```

- `horizon_hours`: 24 или 48.
- `turbine_ids`: непустой список без повторов.
- `refresh_weather=true`: заново проверить источник в пределах исторического
  ограничения `as_of`. Этот флаг не разрешает использовать более поздние выпуски.
- Если настройки времени ещё не подтверждены, сервер возвращает
  `CONFIGURATION_REQUIRED`, а не назначает часовой пояс незаметно.

Ответ `202 Accepted`:

```json
{"run_id": "run_example", "status": "queued"}
```

## Статус и события

`GET /api/agent/runs/run_example`

```json
{
  "run_id": "run_example",
  "status": "running",
  "stage": "weather",
  "progress": 0.25,
  "agent_mode": "policy",
  "as_of": "2026-01-31T18:00:00Z",
  "horizon_hours": 48,
  "turbine_ids": [1, 2],
  "revision": 1,
  "supersedes_run_id": null,
  "reused_run_id": null,
  "events": [],
  "warnings": [],
  "error": null
}
```

`status`: `queued`, `running`, `completed`, `failed`.

`stage`: `validate`, `weather`, `prepare`, `model`, `predict`, `review`, `save`.
`progress`: число 0…1; это ход выполнения задания, не точность модели.

Каждое событие: `id`, `timestamp`, `stage`, `level` (`info`/`warning`/`error`),
`message`, `tool` (имя инструмента или `null`), `attempt`.
Записи добавляет сервер по фактическим действиям.

`revision` — версия результата. `supersedes_run_id` связывает перерасчёт с прежним
результатом. Если после проверки входы не изменились, `reused_run_id` указывает
на результат, который можно использовать повторно; это отражается в событиях.

## Почасовой результат

`GET /api/agent/runs/{run_id}/forecast`

Ответ содержит:

| Поле | Тип | Смысл |
|---|---|---|
| `run_id` | string | ID запуска |
| `as_of` | datetime | Момент решения |
| `horizon_hours` | int | 24 или 48 |
| `unit` | string | `normalized_power` |
| `model_version` | string | Версия обученной модели |
| `training_data_available_until` | datetime | Последняя доступная обучающая цель |
| `series` | array | Один объект на турбину |
| `analysis.summary` | string | Краткое объяснение результата |
| `analysis.warnings` | array of string | Предупреждения |

Каждый объект `series`:

- `turbine_id`;
- `storage_run_id`: числовой `run_id` записи этой турбины в DuckDB;
- `points`: массив из 24/48 объектов `valid_time`, `lead_hour`, `predicted_power`;
- `weather`: `provider`, `model`, `initialization_time`, `available_at`,
  `availability_basis`, `retrieved_at`, `sha256`.

`available_at` — время доступности погодного выпуска, установленное по метаданным
источника или по явно указанной консервативной задержке публикации.
`availability_basis` сообщает, какой способ применён. `retrieved_at` показывает
фактическое время скачивания архива сегодня и может быть позднее `as_of`.
Ключевая проверка: `available_at <= as_of`.

Интервалы неопределённости и фактические значения февраля в первую версию
контракта не входят. Их нельзя рисовать как доступные данные без расчёта/источника.

CSV: UTF-8, одна строка на турбину и прогнозный час:

```text
run_id,as_of,turbine_id,valid_time,lead_hour,predicted_power,weather_initialization_time,weather_available_at,model_version
```

Это внутренний формат экспорта; при получении официального шаблона сдачи
добавляется преобразование в него.

## Ежедневное воспроизведение

`POST /api/agent/replays`

```json
{
  "first_as_of": "2026-01-31T18:00:00Z",
  "last_as_of": "2026-02-28T18:00:00Z",
  "step_hours": 24,
  "horizon_hours": 48,
  "turbine_ids": [1, 2]
}
```

Ответ `202`: `replay_id`, `status`. Прогресс: `status`, `total_runs`,
`completed_runs`, `failed_runs`, `run_ids`, `error`.
Границы моментов решения включительны. Полные горизонты сохраняются даже если
выходят за февраль; фильтрация оценочного периода выполняется отдельно.

## Связь с DuckDB

Используем существующий `src/storage.py`, подробные сигнатуры — в `CHANGELOG.md`.

| API | Хранилище |
|---|---|
| `as_of` | `record_run(issued_at=...)` — симулируемый момент решения |
| `turbine_id` | `1` или `2` |
| `valid_time` | `ForecastRow.target_ts` |
| `predicted_power` | `ForecastRow.predicted_power` |
| `lead_hour` | `lead_hours`, вычисленный хранилищем |
| `model_version` | `forecast_runs.model_version` |
| `storage_run_id` | числовой `forecast_runs.run_id` для одной турбины |

Строковый `run_id` API идентифицирует всё задание, в том числе обе турбины.
Это отдельный идентификатор от числового `run_id` DuckDB. Фронт передаёт
строковый идентификатор из ответа `POST /agent/runs` без преобразований.

Текущая схема использует `TIMESTAMP` без зоны. Серверный адаптер нормализует
даты в UTC перед записью и возвращает `Z` при сериализации. Исходную временную
зону CSV всё равно требуется подтвердить отдельно.

Для будущего графика ревизий используется `store.revisions()`. Метрики из
`store.accuracy_by_lead()` относятся к последним прогнозам на каждый час;
оценка всех выпусков отдельно потребует дополнительного запроса.

## Ошибки

```json
{
  "error": {
    "code": "WEATHER_UNAVAILABLE",
    "message": "Не найден доступный погодный выпуск для выбранного момента.",
    "retryable": true
  }
}
```

Для завершившегося ошибкой фонового задания такой объект находится в его поле
`error`, а `status` равен `failed`. HTTP-ошибки маршрутов используют тот же формат.

Основные коды: `VALIDATION_ERROR`, `CONFIGURATION_REQUIRED`, `WEATHER_UNAVAILABLE`,
`DATA_QUALITY_ERROR`, `RUN_NOT_FOUND`, `RESULT_NOT_READY`, `MODEL_ERROR`.
В интерфейсе показываются сообщение и возможность повторения, если `retryable=true`.
