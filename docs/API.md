# API для фронта — контракт v0.3

**Статус:** маршруты реализованы в `backend/app/`, точка входа — `src.api:app`.
Агент подключён. Прогнозирование требует настроек времени CSV и их подтверждения
либо явного исследовательского режима. Примеры показывают формат ответа.
Схемы: [OpenAPI](../backend/openapi.json). Подключение агента:
[agent-integration.md](backend/agent-integration.md).

Базовый путь: `/api`. При локальной разработке сервер планируется на порту 8000.
Фронт проксирует `/api` на сервер. Опрос статуса раз в 1–2 секунды достаточен
для первого рабочего сценария.

Сценарий NOAA проверен через API. После подключения frontend выполнялись
статические проверки; браузер и Docker в рамках интеграции не запускались.

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
| GET | `/agent/runs?limit=100` | Последние сохранённые запуски, включая ошибки и незавершённые задания |
| GET | `/agent/runs/{run_id}` | Статус, текущий шаг, события и ошибки |
| GET | `/agent/runs/{run_id}/forecast` | Почасовые результаты и происхождение |
| GET | `/agent/runs/{run_id}/forecast.csv` | Скачать тот же результат в CSV |
| POST | `/agent/replays` | Последовательность ежедневных прогнозов |
| GET | `/agent/replays/{replay_id}` | Прогресс последовательности и ID её запусков |
| GET | `/help/status` | Конфигурация помощника OpenAI GPT-6 Astra без секретов |
| POST | `/help/chat` | Ответ помощника по контексту сайта |
| GET | `/integrations/nvidia` | Конфигурация NVIDIA NIM без секретов |
| POST | `/integrations/nvidia/check` | Проверочный вызов NIM |
| POST | `/agent/runs/{run_id}/explanation` | Необязательное пояснение NIM для готового выпуска |

## Готовность и данные

`GET /api/health` возвращает `status: "ok"`, `agent_configured`,
`time_configuration_ready`, `time_configuration_confirmed`, `research_mode`,
`turbines_count`. Проверяет доступ к DuckDB.
`status: "ok"` означает готовность API; возможность нового расчёта определяется
отдельными признаками агента и времени.

`GET /api/data/summary`:

- `unit: "normalized_power"`;
- `time_configuration`: `source_timezone`, `timestamp_meaning`, `confirmed`,
  `missing_fields`;
- `turbines`: `turbine_id`, `file`, `sha256`, `rows`, `start_local`, `end_local`,
  `source_matches_audit`, `missing_percent`, `missing_10min_records`, `full_hours`,
  `partial_hours`, `empty_hours`, `january_2026_complete`, `records_from_february_2026`;
- `february_actuals_available`, `february_metrics` (пока `null`), `warnings`.

`start_local`/`end_local` — исходные текстовые метки CSV, не UTC datetime.
Пока пояс не подтверждён, их нельзя самостоятельно преобразовывать в UTC.
Показатели берутся из отчёта аудита, SHA-256 сверяется с текущими CSV.
При несовпадении новый расчёт отклоняется с `DATA_QUALITY_ERROR`.

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

## История запусков

`GET /api/agent/runs?limit=100` возвращает `{"items": [...]}`. Каждый элемент —
тот же объект статуса, что у `GET /agent/runs/{run_id}`, со стадией, событиями,
ошибками и связями ревизий. Новые задания идут первыми по времени создания;
`limit` — целое 1…200, по умолчанию 100. Список читается из DuckDB,
поэтому сохраняется между сессиями браузера и перезапусками API.

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
- Если время не настроено либо не подтверждено без явно разрешённого
  исследовательского режима, сервер возвращает `CONFIGURATION_REQUIRED`.

Ответ `202 Accepted`:

```json
{"run_id": "run_example", "status": "queued"}
```

Заголовок `Location` указывает на маршрут статуса. Запуск хранится в DuckDB
до отправки ответа; вычисления идут в рабочем потоке. Повторный POST создаёт
новое задание проверки входов. Переиспользование результата определяется после
работы агента по хешу входов, а не по одному совпадению тела HTTP-запроса.

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
- `points`: массив из 24/48 объектов `valid_time`, `lead_hour`, `predicted_power`,
  `wind_speed_100m`, `wind_speed_10m`, `temperature_2m`, `weather_inputs`.
  Погодные поля — значения того же прогноза погоды, по которому рассчитана
  мощность (м/с и °C); для Previous Runs это среднее по моделям. В выпусках,
  сохранённых до появления этих полей, они равны `null`;
- `weather.sources`: каталог всех использованных погодных ответов для этой серии.

Источник содержит `source_id`, `provider`, `model`, `product`, `initialization_time`,
`available_at`, `availability_basis`, `retrieved_at`, `sha256`.
`product` различает `single_run` и `previous_runs`.

У каждого часа `weather_inputs` — непустой список ссылок `source_id` на каталог,
с полями `forecast_offset_days` и `available_at_estimate`. Так сохраняются отдельно
GFS/ICON, разные месячные ответы и offsets каждого прогнозного часа.

Для `single_run` даты выпуска и доступности обязательны, проверяется
`initialization_time <= available_at <= as_of` и `available_at <= retrieved_at`.
У ссылки на такой источник `forecast_offset_days` и `available_at_estimate` — `null`.

Для `previous_runs` `initialization_time` и `available_at` всегда `null`.
У ссылки обязательны `forecast_offset_days` (целое 1…7) и `available_at_estimate`.
Поддерживаемая политика `availability_basis = previous_runs_offset_plus_12h_v1`:

```text
available_at_estimate = valid_time - forecast_offset_days * 24h + 12h
available_at_estimate <= as_of
```

Backend заново вычисляет оценку и отклоняет несовпадение, неизвестную политику,
неизвестные/повторные ссылки и повтор модели в одном прогнозном часу.
Каждый объявленный источник должен использоваться хотя бы одним часом.
`retrieved_at` — фактическое скачивание архива, оно может быть позже `as_of`.

Политика +12 часов остаётся допущением команды. Backend добавляет предупреждение
в журнал, `warnings` задания и `analysis.warnings` результата. Проверка этой оценки
не доказывает фактическое время публикации. Пример для фронта и точное отображение:
[weather-provenance.md](backend/weather-provenance.md).

Старые сохранённые ответы с единственным объектом `weather` преобразуются при чтении
в `weather.sources` и ссылки у точек. JSON в БД не переписывается. Фронт должен
использовать структуру v0.3 из OpenAPI.

Интервалы неопределённости и фактические значения февраля в первую версию
контракта не входят. Их нельзя рисовать как доступные данные без расчёта/источника.

CSV: UTF-8, одна строка на турбину и прогнозный час:

```text
run_id,as_of,turbine_id,valid_time,lead_hour,predicted_power,wind_speed_100m,wind_speed_10m,temperature_2m,weather_initialization_time,weather_available_at,model_version,weather_available_at_estimate,weather_availability_basis,weather_inputs_json
```

Три погодные колонки после `predicted_power` пустые для старых выпусков.
Остальные колонки сохранены. `weather_initialization_time` заполнена только
для единственного источника Single Run у данного часа. `weather_available_at`
содержит максимальное известное время доступности, если оно известно для всех
входов; при наличии Previous Runs остаётся пустой. Если есть оценки,
`weather_available_at_estimate` содержит максимум времён доступности всех входов
(точных и оценочных). Неизвестные даты — пустые ячейки.
`weather_inputs_json` хранит JSON-массив полных метаданных всех источников данного
часа вместе с offsets и оценками, включая хеши. Отдельные модели не дублируют
строки мощности в CSV. Формат CSV определяется названиями колонок.

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

Шаг первой версии — строго 24 часа. Разность границ должна быть кратна шагу.
По умолчанию разрешены до 62 запусков в replay и 128 одновременно принятых
незавершённых запусков. Все дочерние `run_ids` доступны после принятия replay.
Ошибка одного запуска не отменяет следующие; replay завершается `failed`,
если хотя бы один дочерний запуск неуспешен. Счётчики отражают фактические статусы.

После перезапуска API незавершённые задания получают `JOB_INTERRUPTED`;
готовые результаты остаются доступны. Повторять запуск нужно новым POST.

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

Для Previous Runs и набора из нескольких источников `forecast_runs.weather_run`
равен SQL `NULL`. Полное происхождение хранится в `api_runs.result`; поле `note`
содержит строковый API run_id. Схема `src/storage.py` не изменяется.

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

| HTTP | Ситуация |
|---|---|
| 404 | RUN_NOT_FOUND, REPLAY_NOT_FOUND |
| 409 | CONFIGURATION_REQUIRED, RESULT_NOT_READY, изменённый CSV / DATA_QUALITY_ERROR |
| 422 | VALIDATION_ERROR |
| 429 | QUEUE_FULL |
| 503 | AGENT_NOT_CONFIGURED, SERVER_STOPPING, недоступный аудит / DATA_QUALITY_ERROR |
| 500 | INTERNAL_ERROR |

Ошибки фонового выполнения читаются через GET статуса с HTTP 200 и
`status: "failed"`. Дополнительные коды: `JOB_INTERRUPTED`, `AGENT_LIMIT_EXCEEDED`,
`REPLAY_FAILED`. При ошибке расчёта маршрут результата возвращает 409.

## Помощник сайта OpenAI ASTRA

`GET /api/help/status` возвращает `provider=openai`, `model=gpt-6-astra`,
`auth_mode` (`api_key` или `chatgpt`), `enabled`, `configured`, `available`,
`prompt_version`. `available` означает наличие включённого подключения: ключа
либо локального входа Codex через ChatGPT. Доступ к модели проверяется при вопросе.

`POST /api/help/chat`:

```json
{
  "message": "Где посмотреть погоду для этого прогноза?",
  "history": [],
  "run_id": null,
  "context": {
    "view": "forecast",
    "mode": "forecast",
    "locale": "ru",
    "date": "2026-02-01",
    "horizon_hours": 48,
    "simulation_hours": null,
    "turbine_ids": [1, 2]
  }
}
```

- `message`: непустой текст до 2000 символов;
- `history`: до 8 сообщений `{role: user|assistant, content}`, до 3000 символов каждое;
- `run_id`: ID выбранного запуска формата `run_` + 32 hex-символа либо `null`;
- `context.view`: `overview`, `forecast`, `agent`, `sources`, `history`;
- `context.mode`: `forecast` (по умолчанию) либо `simulation`; в симуляции сервер
  игнорирует `run_id`, не подмешивает сохранённый прогноз и не даёт кнопку его CSV;
- `context.locale`: `ru` (по умолчанию), `en`, `kk` — язык ответа ASTRA;
- `context.simulation_hours`: длительность синтетического сценария либо `null`;
- `context.date`: дата **начала прогноза** в интерфейсе, не as_of; допускается `null`;
- горизонт 24/48 и номера турбин используют ту же валидацию, что запуск прогноза.

Сервер сам читает выпуск по ID. Отсутствующий выпуск не подменяется другим:
помощник получает признак недоступности и предлагает перейти в историю.

Ответ содержит `provider` (`openai` либо `local_help`), `model` (ASTRA или `null`),
`text`, `sources`, `actions`, `warning`, `prompt_version`.

Источник: `{id, title, view}`. Действие:
`{type: navigate|download_csv, label, view, run_id}`.
Неприменимые поля `view`/`run_id` равны `null`. Все ID источников и кнопок проверяются
по серверному списку. При ответе модели `model` может содержать snapshot `gpt-6-astra-*`.

Без доступного подключения или при сбое OpenAI возвращается HTTP 200 с `provider=local_help`,
`model=null` и пояснением в `warning`. **Не подписывайте такой ответ как ASTRA.**
Некорректный вход возвращает 422. Лимит внешних обращений — 20 в минуту и 2
одновременно на процесс; превышение включает обычную справку.

Чат не меняет прогнозы, не запускает задачи и не пишет историю в DuckDB.
Кнопку пользователь нажимает сам; CSV доступен для соответствующего завершённого
выпуска. [Настройки и системный промпт](AI-HELP.md).

## Необязательный NVIDIA NIM

- `GET /api/integrations/nvidia`: `enabled`, `configured`, `model`, `purpose`.
- `POST /api/integrations/nvidia/check`: выполняет реальный вызов модели;
  без ключа/включения — 409 `CONFIGURATION_REQUIRED`, сбой — 503 `NVIDIA_UNAVAILABLE`.
- `POST /api/agent/runs/{run_id}/explanation`: поясняет готовый выпуск.
  Неизвестный ID — 404, незавершённый выпуск — 409.

Пояснение: `{provider: nvidia|policy, model, text, warning, generated_at}`.
При отключённом NIM или ошибке API возвращается реальный исходный анализ агента
с `provider=policy`. Численный прогноз не меняется. `generated_at` — время пояснения,
а момент исторического решения остаётся в `forecast.as_of`.
[Подключение и обучение на GPU](NVIDIA.md).
