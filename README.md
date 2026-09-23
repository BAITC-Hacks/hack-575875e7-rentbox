# RentBox — прогноз выработки ВЭС

Проект команды RentBox для HackAlem AI, трек «Энергетика».
Цель — агент, который получает архивные погодные прогнозы, доступные на момент
решения, и рассчитывает почасовую нормализованную мощность двух турбин
на 24–48 часов. Тестовый период — февраль 2026 года.

## Быстрый старт

Одна команда — поднимает сервис и считает прогноз на 48 часов:

```bash
./run.sh demo
```

Скрипт сам проверит окружение, создаст `.env`, соберёт образ, дождётся готовности
сервиса, запустит расчёт и сохранит результат в `artifacts/demo-forecast.csv`.

Результат — 96 почасовых значений для двух турбин с происхождением погоды.

Остальные команды:

| Команда | Что делает |
|---|---|
| `./run.sh` | поднять сервис и показать адреса |
| `./run.sh all` | поднять backend и дашборд вместе |
| `./run.sh demo` | поднять и сразу посчитать прогноз |
| `./run.sh check` | только проверить окружение, ничего не запуская |
| `./run.sh logs` | последние 50 строк журнала |
| `./run.sh stop` | остановить |

**Ключи и учётные записи не нужны.** Архивные прогнозы погоды лежат в репозитории
(`data/gfs-runs`, 730 ежедневных циклов), основная модель — в `artifacts/gfs-model`.
Интернет требуется при
первой сборке образа, чтобы скачать зависимости.

Нужен Docker. Если его нет, но есть `uv`, скрипт поднимет сервис локально.
Порт занят — возьмёт следующий свободный; можно задать свой: `BACKEND_PORT=9000 ./run.sh`.

Ниже — подробности: установка по шагам, ручной запуск, API, обучение модели.


## Текущее состояние

Данные проверены, есть DuckDB-хранилище, обученная модель по операционным
прогнозам NOAA GFS и ежедневный расчёт февраля. Поиск 400 моделей завершён
на RTX 5090, CPU и NVIDIA Brev A6000. Backend дашборда реализован:
каталог турбин, сводка данных, очередь запусков, статусы и события, ревизии,
CSV и replay. Агент подключён к API; с основной моделью завершены все 29
ежедневных выпусков без ошибок: [отчёт replay](reports/agent-noaa-replay.json).
Dashboard Windcast на Next.js готов и пока работает на синтетических данных.
Подключение интерфейса к backend ещё не выполнено.

**Временные настройки пока исследовательские:** CSV считаются UTC+5, метки —
началом десятиминутного интервала, выпуск — в 23:00 по этим часам. Требуется
подтверждение организаторов. Все результаты явно помечены этим допущением.

- [Задание и критерии](docs/hackathon/track-energy.md)
- [Журнал изменений и интерфейсы для совместной работы](CHANGELOG.md)
- [План работы и распределение задач](docs/PLAN.md)
- [Контракт API для фронта](docs/API.md), [OpenAPI](backend/openapi.json)
- [Подключение дашборда к backend](docs/frontend-integration.md) и [живые примеры ответов](docs/samples/)
- [Устройство backend](backend/README.md)
- [Интерфейс подключения агента](docs/backend/agent-integration.md)
- [Результаты проверки данных](reports/data-audit.md)
- [Скрипт проверки](scripts/audit_data.py)
- [Протокол исторического прогноза без будущей информации](docs/FORECAST_PROTOCOL.md)
- [Ансамбль NOAA GFS, январские метрики и ограничения оценки](artifacts/gfs-model/report.md)
- [Прогнозы февраля, включая мартовский хвост 48-часовых выпусков](artifacts/gfs-model/february_replay.csv)
- [Требования кейса и их реализация](docs/REQUIREMENTS.md)

Готовый ансамбль NOAA GFS: январская MAE **0.15947**, RMSE **0.23190** в долях
нормализованной мощности. Первый бустинг давал MAE 0.19420,
предыдущий ансамбль — 0.16933, персистенция последнего часа — 0.34268.
Подбор моделей —
на ноябре–декабре; январь после первого эксперимента используется для мониторинга
разработки. Качество февраля неизвестно: фактических значений этого месяца нет.

## Архитектура и технологии

```text
Frontend (планируемое подключение) → FastAPI /api → очередь → Python-модуль агента
                         ↓                 ↓
                  статусы и события   результат + происхождение
                         └──── DuckDB / ForecastStore ────┘
```

Конвейер прогноза: `data/incoming` → полные часы из 6 измерений → архивы
NOAA GFS с проверкой публикации → признаки погоды и календаря → выбор модели
по прошлому периоду → почасовой прогноз → анализ → запись в DuckDB.
При обновлении входов агент создаёт ревизию; одинаковые входы переиспользуют
сохранённый расчёт. История хранится через `src/storage.py`.

Python 3.12, FastAPI, Pydantic, DuckDB, NumPy, pandas, scikit-learn.
Зависимости прогноза — [requirements.txt](requirements.txt); зависимости
backend и точные версии — [pyproject.toml](backend/pyproject.toml)
и [uv.lock](backend/uv.lock).

Общая точка входа — `src.api:app`; HTTP-слой находится в `backend/app/`.
Один процесс Uvicorn и один поток исполнения агента.
ML-числа, происхождение погоды и решения предоставляет модуль агента.

## Dashboard (frontend)

Dashboard Windcast на русском, английском и казахском: прогноз на 24/48 часов, две турбины,
интерактивный график, таблица с CSV-экспортом, имитация AI-агента и история запусков.
Интерфейс использует синтетические данные и пока не подключён к Python-модели или API.

Node.js 22.20+ и npm 11. Из корня репозитория:

```bash
npm install
npm run dev
```

Открыть http://localhost:3000. [Устройство frontend, проверки и ограничения](docs/FRONTEND.md).

Версия дизайна v2 находится в ветке `design/dashboard-v2`: KPI над графиком, компактная 3D-панель, единая шкала времени и кликабельные выводы. Язык выбирается в шапке и сохраняется в браузере; переключение не сбрасывает прогноз. Предыдущая версия сохранена тегом `dashboard-before-v2`; инструкция по возврату — в [документации frontend](docs/FRONTEND.md#dashboard-v2-and-languages).

## Установка и зависимости

### Прогноз из командной строки

Python 3.12. Расчёт готовой модели работает на CPU без PyTorch.
Версии зависимостей зафиксированы в `requirements.txt`.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

### Backend дашборда

Из корня проекта на Mac / Linux. Нужны Python с pip и make;
uv установит Python 3.12 в .tools/python, окружение — в backend/.venv.

```bash
python3 -m pip install --target .tools uv==0.12.18
make dev
```

Если uv уже установлен, достаточно `make dev`. Для запуска без reload —
`make run`. Системный Python не заменяется.

- Swagger: http://localhost:8000/docs
- OpenAPI: http://localhost:8000/openapi.json
- API: http://localhost:8000/api

⚠️ **`.env` нужен для расчёта.** Сервис поднимется и без него, но запуск агента
вернёт `CONFIGURATION_REQUIRED`: не заданы настройки времени исходных измерений.
`./run.sh` создаёт `.env` сам, с исследовательским допущением (UTC+5, метка —
начало интервала) и пометкой `research`. Вручную:

```bash
cp .env.example .env
cat >> .env <<'SETTINGS'
RENTBOX_SOURCE_TIMEZONE=Etc/GMT-5
RENTBOX_TIMESTAMP_MEANING=interval_start
RENTBOX_ALLOW_RESEARCH_TIME_SETTINGS=true
SETTINGS
```

Когда организаторы подтвердят семантику времени, эти значения нужно заменить
на подтверждённые и убрать `allow_research`. Остальные параметры — в
[.env.example](.env.example). Окружение локально подготовлено на MacBook Air M5 /
Apple Silicon и проверено на Linux с Docker.

### Запуск через Docker

Нужен Docker с Compose 2.24+:

```bash
docker compose up --build
```

Контекст сборки — корень репозитория. CSV, отчёт и серверные модули включаются
в образ; DuckDB хранится в именованном томе forecast_state.
Остановка: `docker compose down`; том при этом сохраняется.
Первая установка зависимостей и образов требует интернет.

## Запуск и проверка без собственных ключей

Из корня репозитория после установки зависимостей из `requirements.txt`:

```bash
python -m scripts.predict --as-of 2026-01-31T18:00:00Z --horizon 48
```

Результат — `artifacts/prediction.csv`, 96 строк (48 часов × 2 турбины),
мощность в [0, 1]. Используются настоящие сохранённые погодные прогнозы
и обученная модель; API-ключи, сеть, GPU и личные аккаунты для этого не нужны.
Загрузка `joblib` допустима только для доверенных файлов этого проекта.

Каталог турбин, сводка данных, очередь и сохранённая история в API также
не требуют аккаунтов. Агент `src.agent:create_agent` работает в режиме policy:
проверяет входы и доступность погоды, рассчитывает, анализирует, сохраняет через
backend. Совпадение входов переиспользует прогноз, изменения создают ревизию.

Исследовательский запуск полного API одной командой:

```bash
make demo
```

Команда явно выбирает UTC+5 и начало интервала; `confirmed=false` остаётся
в данных. Это временная конфигурация до ответа организаторов.

## Основной сценарий через API

После запуска сервера:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/turbines
curl http://localhost:8000/api/data/summary
```

Health проверяет доступ к DuckDB и показывает agent_configured и
time_configuration_ready. Каталог содержит две реальные турбины.
Сводка берётся из аудита с проверкой SHA-256 исходных CSV.

После `make demo` либо настройки подтверждённого времени:

```bash
curl -i http://localhost:8000/api/agent/runs \
  -H 'Content-Type: application/json' \
  -d '{"as_of":"2026-01-31T18:00:00Z","horizon_hours":48,"turbine_ids":[1,2],"refresh_weather":false}'
```

Дата показывает формат запроса; время ежедневного выпуска ещё не утверждено.
Ответ 202 содержит run_id и Location. Опрос статуса — раз в 1–2 секунды.
После completed: GET /api/agent/runs/{run_id}/forecast либо /forecast.csv.
Для ежедневной последовательности — POST /api/agent/replays; форматы в API.md.

Без подтверждения или явно включённого исследовательского режима POST возвращает
409 CONFIGURATION_REQUIRED. Отключённый агент — 503 AGENT_NOT_CONFIGURED.
API не возвращает выдуманные прогнозы.

## Обучение модели

Основной ансамбль NOAA GFS (GPU нужен для повторного обучения MLP):

```bash
# Готовые 730 циклов уже в git. Загрузка пропущенных дней требует ecCodes и сети.
python -m scripts.fetch_gfs_runs --start 2024-03-01 --end 2026-02-28
python -m scripts.train_gfs prepare
python -m scripts.train_gfs train --worker cpu
python -m scripts.train_gfs train --worker local-gpu
python -m scripts.train_gfs train --worker cloud-gpu
# При обучении на двух машинах объединить каталоги workers в artifacts/gfs-search.
python -m scripts.train_gfs finalize
```

Для обучения использован PyTorch 2.11.0+cu128, для загрузки GRIB — ecCodes 2.48.0
(включён в зависимости backend). PyTorch не включён в обязательные
зависимости инференса. Предыдущие исследования GFS/ICON сохранены в
`artifacts/ensemble/` и `artifacts/expanded/`, их скрипты — `search_models.py`
и `finalize_search.py`. Кривая `scripts/train_power_curve.py` — отдельный опыт
с фактическим ветром; его MAE нельзя выдавать за ошибку прогноза на сутки.

## Конфигурация

| Переменная | По умолчанию / назначение |
|---|---|
| RENTBOX_AGENT_FACTORY | src.agent:create_agent |
| RENTBOX_MODEL_DIR | artifacts/gfs-model, если артефакт есть; иначе artifacts/ensemble |
| RENTBOX_GFS_CACHE | data/gfs-runtime; /app/state/gfs в Docker. Копируется из сохранённого архива |
| RENTBOX_SOURCE_TIMEZONE | Не задан; часовой пояс CSV в формате IANA |
| RENTBOX_TIMESTAMP_MEANING | Не задан; interval_start либо interval_end |
| RENTBOX_TIME_CONFIGURATION_CONFIRMED | false; подтверждение двух настроек выше |
| RENTBOX_ALLOW_RESEARCH_TIME_SETTINGS | false; явное разрешение расчёта с неподтверждёнными временными настройками |
| RENTBOX_DATABASE_PATH | data/forecasts.duckdb относительно проекта; /app/state/forecasts.duckdb в Docker |
| RENTBOX_CORS_ORIGINS | JSON-массив: http://localhost:5173 и http://localhost:3000 |
| RENTBOX_MAX_PENDING_RUNS | 128 |
| RENTBOX_MAX_REPLAY_RUNS | 62 |
| RENTBOX_MAX_EVENTS_PER_RUN | 500 |
| BACKEND_PORT | 8000, порт Docker Compose на хосте |

Локально читается корневой .env, затем backend/.env; переменные процесса
имеют приоритет. В Docker корневой .env передаётся как окружение.
Часовой пояс и смысл меток следует получить от организаторов.
Пустые значения не означают UTC. Для расчёта из командной строки переменные
окружения не нужны; время выпуска и горизонт задаются CLI.

## Параметры и ограничения

- Факта февраля нет, качество измеряется на январе. Повторные выпуски считаются
  отдельно. Метрики февраля в API возвращаются null.
- Предсказывается нормализованная мощность каждой турбины 0–1, не МВт или МВт·ч.
- Основная модель использует NOAA GFS: `initialization_time` проверяется в GRIB,
  `available_at` берётся из исходных S3 Last-Modified и должно быть `<= as_of`.
  Между трёхчасовыми опорами одного цикла выполняется интерполяция.
  Текущий обученный сценарий — ежедневный выпуск в 18:00 UTC, горизонт 24/48 ч.
- В предыдущих исследовательских моделях архив Previous Runs содержит значения с фиксированной заблаговременностью,
  а не полные отдельные циклы. Точная историческая публикация не возвращается.
  В API v0.3 неизвестные `initialization_time` и `available_at` остаются `null`.
  Для каждого прогнозного часа сохраняются использованные источники GFS/ICON,
  offset и `available_at_estimate = valid_time - offset*24h + 12h`.
  Backend пересчитывает оценку и требует `available_at_estimate <= as_of`.
  Запас 12 часов — допущение; проверка формулы не доказывает историческую
  доступность. Формат и примеры: [метаданные погоды](docs/backend/weather-provenance.md).
- Время CSV не подтверждено; автоматической подстановки пояса нет.
  Подтверждение времени и меток интервалов может потребовать переобучения.
- Реализация предполагает один процесс-писатель DuckDB. После перезапуска
  незавершённые задания помечаются JOB_INTERRUPTED, готовые результаты сохраняются.
- Модуль агента обязан ограничивать время инструментов и реагировать на остановку.
- Сценарий NOAA выполнен через настоящий API: 29 из 29 запусков.
  Предыдущую Docker-версию Claude проверил из чистого клона (см. CHANGELOG).
  Docker-сборку после подключения NOAA нужно повторить перед сдачей.
  Публичного развёртывания пока нет.

Команды разработчика: `make openapi`, `make lint`, `make test`.
Аудит данных: `python scripts/audit_data.py` в окружении с pandas и numpy.

## Внешние материалы

| Материал | Источник | Лицензия / условия |
|---|---|---|
| CSV двух турбин | Организаторы, ссылки в `reports/data-audit.md` | Предоставлены для кейса; отдельная открытая лицензия не указана |
| Операционные прогнозы NOAA GFS | [NOAA GFS в AWS](https://registry.opendata.aws/noaa-gfs-bdp-pds/) | Открытые данные NOAA; использовать с указанием источника. Сохранены точки, метаданные и хэши GRIB-полей |
| Архивные прогнозы GFS / ICON | [Open-Meteo](https://open-meteo.com/en/docs/previous-runs-api), NOAA / DWD | [CC BY 4.0](https://open-meteo.com/en/licence); исходные ответы сохранены, признаки преобразованы нами |
| ecCodes, чтение GRIB | [ECMWF ecCodes](https://github.com/ecmwf/eccodes-python) | Apache-2.0 |
| Python | [python.org](https://www.python.org/) | PSF |
| FastAPI | [fastapi.tiangolo.com](https://fastapi.tiangolo.com/) | MIT |
| Pydantic / settings | [docs.pydantic.dev](https://docs.pydantic.dev/) | MIT |
| NumPy, pandas, scikit-learn | [NumPy](https://numpy.org/), [pandas](https://pandas.pydata.org/), [scikit-learn](https://scikit-learn.org/) | BSD-3-Clause |
| Joblib, threadpoolctl | [Joblib](https://joblib.readthedocs.io/), [threadpoolctl](https://github.com/joblib/threadpoolctl) | BSD-3-Clause |
| HTTPX / Uvicorn | [python-httpx.org](https://www.python-httpx.org/), [uvicorn.org](https://www.uvicorn.org/) | BSD-3-Clause |
| DuckDB | [duckdb.org](https://duckdb.org/) | MIT |
| PyArrow | [Apache Arrow](https://arrow.apache.org/) | Apache-2.0 |
| PyTorch, только обучение | [PyTorch](https://pytorch.org/) | BSD-3-Clause |
| CatBoost, дополнительное обучение на Brev | [CatBoost](https://github.com/catboost/catboost) | Apache-2.0; в обязательные зависимости инференса не входит |
| uv | [docs.astral.sh](https://docs.astral.sh/uv/) | MIT / Apache-2.0 |
| pytest / Ruff | [pytest.org](https://docs.pytest.org/), [docs.astral.sh/ruff](https://docs.astral.sh/ruff/) | MIT |

| next (frontend) | [npm](https://www.npmjs.com/package/next) | MIT |
| react (frontend) | [npm](https://www.npmjs.com/package/react) | MIT |
| shadcn (frontend) | [npm](https://www.npmjs.com/package/shadcn) | MIT |
| @base-ui/react (frontend) | [npm](https://www.npmjs.com/package/@base-ui/react) | MIT |
| tailwindcss (frontend) | [npm](https://www.npmjs.com/package/tailwindcss) | MIT |
| typescript (frontend) | [npm](https://www.npmjs.com/package/typescript) | Apache-2.0 |
| turbo (frontend) | [npm](https://www.npmjs.com/package/turbo) | MIT |
| lucide-react (frontend) | [npm](https://www.npmjs.com/package/lucide-react) | ISC |
| next-themes (frontend) | [npm](https://www.npmjs.com/package/next-themes) | MIT |
| tw-animate-css (frontend) | [npm](https://www.npmjs.com/package/tw-animate-css) | MIT |
| class-variance-authority (frontend) | [npm](https://www.npmjs.com/package/class-variance-authority) | Apache-2.0 |
| zod (frontend) | [npm](https://www.npmjs.com/package/zod) | MIT |
| cn (frontend) | [npm](https://www.npmjs.com/package/cn) | MIT |

Погодные данные: [Weather data by Open-Meteo.com](https://open-meteo.com/).
Транзитивные зависимости backend закреплены в uv.lock.

## Заранее подготовленные компоненты

Организационная документация и служебные скрипты подготовлены до реализации.
Для обучения использовано подготовленное локальное Python/CUDA-окружение.
Код прогнозирования, каркас backend и API написаны под кейс в этом
репозитории 23.09.2026. Для dashboard использованы Next.js и shadcn/ui
(Vega, Base UI); интерфейс пока работает на моковых данных.

## AI-инструменты и вклад участников

Codex — аудит, погода, обучение, прогноз, backend, документация и контракт API;
Claude Code — DuckDB-хранилище, исправление определения турбин по именам файлов
и бэклог. Разработчик агента отвечает за данные, погоду, модель и цикл агента;
пользователь backend — за HTTP-слой дашборда; коллеги — за интерфейс
в `apps/web/` и `packages/ui/`. Личные вклады подтверждаются историей коммитов; имена
и окончательный вклад команды следует заполнить перед сдачей.
