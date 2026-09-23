# RentBox — прогноз выработки ВЭС

**Почасовой прогноз мощности двух ветротурбин на 24–48 часов.**
Агент получает погодный прогноз, запускает обученную модель, анализирует результат
и сохраняет историю расчётов. Такой прогноз помогает планировать выработку
и заранее видеть ожидаемые изменения мощности.

Проект команды RentBox для **HackAlem AI**, трек «Энергетика».
Выход модели — нормализованная мощность от **0 до 1** для каждой турбины.
Период задания — **1–28 февраля 2026 года**.

[Быстрый старт](#быстрый-старт) · [Что готово](#что-уже-работает) ·
[Результаты](#качество-прогноза) · [Как работает агент](#как-работает-агент) ·
[Ограничения](#известные-ограничения)

## Быстрый старт

**Нужны:** Git, Bash, `curl` и запущенный Docker с Compose 2.24+.
Подойдут Linux, macOS или Windows через WSL2. Если Docker нет, скрипт умеет
запускать backend через установленный `uv`. **GPU и API-ключи не нужны.**
Интернет нужен для первого скачивания образов и зависимостей.

```bash
git clone https://github.com/BAITC-Hacks/hack-575875e7-rentbox.git hack-rentbox
cd hack-rentbox
./run.sh demo
```

Если репозиторий уже скачан, выполните последнюю команду из его корня.
Скрипт настроит окружение, поднимет API и рассчитает прогноз для выпуска
**31 января 2026, 18:00 UTC**.

**Что получится:**

- `artifacts/demo-forecast.csv` — **96 строк: 48 часов × 2 турбины**;
- в каждой строке — целевой час, прогноз мощности, версия модели и происхождение погоды;
- API с интерактивной документацией: [localhost:8000/docs](http://localhost:8000/docs).
  Если выбран другой порт, скрипт напечатает адрес.

> **Настройки времени пока исследовательские:** UTC+5, метка начала
> десятиминутного интервала, ежедневный выпуск в 23:00 по часам CSV.
> Скрипт записывает их в `.env`, только если файла ещё нет.
> Организаторы эти настройки не подтвердили; результаты содержат эту пометку.

### Посмотреть дашборд Windcast

```bash
./run.sh all
```

Дополнительно нужны **Node.js 22.20+ и npm 11**. Скрипт запускает backend
и интерфейс; обычный адрес интерфейса — [localhost:3000](http://localhost:3000).
В дашборде есть график, таблица, история и интерактивная 3D-турбина.

**Дашборд пока показывает синтетические данные.** Подключение к API ещё не завершено.
Реальные результаты модели доступны через `./run.sh demo`, CLI, API и CSV в репозитории.

| Команда | Действие |
|---|---|
| `./run.sh` | Запустить только backend |
| `./run.sh check` | Проверить наличие окружения и файлов |
| `./run.sh logs` | Показать журнал backend |
| `./run.sh stop` | Остановить запущенные сервисы |
| `BACKEND_PORT=9000 ./run.sh demo` | Рассчитать прогноз через указанный порт |

## Что уже работает

| Возможность | Результат / где посмотреть |
|---|---|
| Подготовка предоставленных CSV | Полные часовые средние; [аудит данных](reports/data-audit.md) |
| Загрузка открытых прогнозов по координатам | 730 циклов NOAA GFS с метаданными публикации в `data/gfs-runs/` |
| Обученная модель на 24/48 часов | Ансамбль пяти нейросетей, запускается на CPU; [отчёт](artifacts/gfs-model/report.md) |
| Цикл агента | Получение погоды → подготовка → расчёт → анализ → запись результата |
| Пересчёт и история | Новая ревизия при изменении входов; повторное использование одинаковых входов; DuckDB |
| Воспроизведение февраля | **29 из 29 ежедневных запусков**, 2784 значения; [отчёт выполнения](reports/agent-noaa-replay.json) |
| HTTP API | Очередь, статусы, события, JSON, CSV и запуск последовательности дат; [контракт](docs/API.md) |
| Дашборд | Демонстрационный интерфейс; интеграция с реальными расчётами в работе |

**Готовый прогноз февраля:** [february_replay.csv](artifacts/gfs-model/february_replay.csv).
Каждый выпуск сохраняет полные 48 часов, поэтому последние выпуски захватывают март.
Поле `in_february` выделяет часы целевого месяца.

## Качество прогноза

Измерено по фактической мощности **января 2026**. Чем меньше ошибка, тем лучше.
MAE — средняя абсолютная ошибка; RMSE сильнее учитывает крупные промахи.
Обе метрики выражены в долях нормализованной мощности.

| Модель / горизонт | MAE | RMSE |
|---|---:|---:|
| **Основная модель NOAA, 1–48 ч** | **0.15947** | **0.23190** |
| Та же модель, 1–24 ч | 0.15226 | 0.21898 |
| Та же модель, 25–48 ч | 0.16692 | 0.24453 |
| Базовый прогноз: повтор последнего известного полного часа | 0.34268 | 0.45155 |

MAE 0.15947 означает среднее абсолютное отклонение 0.15947 по шкале 0–1.
Оценка включает 2928 прогнозных строк; один целевой час может встречаться
в нескольких ежедневных выпусках.

400 конфигураций обучались на CPU, RTX 5090 и Brev A6000.
Модели выбирались по ноябрю–декабрю 2025. Январь использовался для мониторинга
нескольких экспериментов и не считается новым независимым тестом.
**Качество февраля неизвестно: фактических значений за этот месяц нет.**
Подробности: [метрики модели](artifacts/gfs-model/metrics.json)
и [сравнение с базовыми прогнозами](artifacts/gfs-model/baselines.json).

## Как работает агент

`as_of` — момент, на который воспроизводится решение. Например,
`2026-01-31T18:00:00Z` означает «прогнозируем, располагая только информацией,
доступной к 18:00 UTC 31 января».

1. **Проверяет входы:** координаты, исходные CSV, временные настройки и конец обучения модели.
2. **Получает погоду:** загружает нужный выпуск NOAA GFS или читает сохранённую копию.
3. **Проверяет доступность:** каждый использованный погодный файл должен быть опубликован к `as_of`.
4. **Рассчитывает прогноз:** готовит признаки и выдаёт по 24/48 значений на турбину.
5. **Анализирует результат:** проверяет допустимость мощности и отмечает резкие изменения по часам.
6. **Сохраняет историю:** при изменении входов создаёт ревизию, при совпадении использует прежний результат.

Агент — контроллер инструментов с заданными правилами (`policy`). LLM в этом
цикле не вызывается. Запуски выполняются через очередь API; последовательность
исторических дат задаётся одним запросом. Для повторного получения погоды
есть `refresh_weather=true`; постоянный фоновый опрос источника не включён.

```mermaid
flowchart LR
    H["История турбин"] --> T["Обучение"] --> M["Сохранённая модель"]
    W["Архив NOAA GFS"] --> A["Агент"]
    M --> A
    Q["HTTP API и очередь"] --> A
    A --> D["DuckDB: прогнозы и ревизии"]
    D --> R["JSON, CSV и история через API"]
```

### Как соблюдается условие о прошлом

Для решения в **18:00 UTC** используется погодный цикл **12:00 UTC**.
Инициализация и горизонт проверяются внутри GRIB, дата публикации — по
исходному S3 `Last-Modified`. Из 17 трёхчасовых опор одного цикла получаются
почасовые значения. Сохраняются URL, даты, диапазоны байтов и SHA-256.
Будущие фактические погода и мощность в признаки прогноза не входят.

[Исторический протокол](docs/FORECAST_PROTOCOL.md) ·
[Соответствие требованиям кейса](docs/REQUIREMENTS.md)

## Запуск без Docker и без собственных ключей

Готовая модель работает на CPU без PyTorch. Для расчёта из сохранённого
архива после установки зависимостей сеть также не нужна.

**Только модель и CSV** — Python 3.12, команды из корня репозитория:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m scripts.predict --as-of 2026-01-31T18:00:00Z --horizon 48
```

Результат — `artifacts/prediction.csv`. Для суток задайте `--horizon 24`.
CLI рассчитывает прогноз; историю и события агента сохраняет backend.

**Полный API** — установленный `uv` и `make`:

```bash
make demo
```

Команда установит зависимости backend и запустит сервер на порту 8000 с явно
заданными исследовательскими настройками времени. Сервер работает в текущем
терминале; остановка — `Ctrl+C`.

## Основной сценарий через API

После запуска откройте [Swagger](http://localhost:8000/docs) или отправьте запрос:

```bash
curl -sS http://localhost:8000/api/agent/runs \
  -H 'Content-Type: application/json' \
  -d '{"as_of":"2026-01-31T18:00:00Z","horizon_hours":48,"turbine_ids":[1,2]}'
```

Ответ содержит `run_id`. По нему доступны:

| Путь | Что возвращает |
|---|---|
| `GET /api/agent/runs/{run_id}` | Статус, прогресс и журнал; дождитесь `completed` |
| `GET /api/agent/runs/{run_id}/forecast` | 96 значений, происхождение погоды и анализ |
| `GET /api/agent/runs/{run_id}/forecast.csv` | Файл CSV |
| `POST /api/agent/replays` | Ежедневные выпуски за заданный период |

Для февраля параметры последовательности: `first_as_of=2026-01-31T18:00:00Z`,
`last_as_of=2026-02-28T18:00:00Z`, `step_hours=24`, `horizon_hours=48`,
`turbine_ids=[1,2]`. [Форматы запросов](docs/API.md) ·
[Пример настоящего ответа NOAA](reports/agent-noaa-first-forecast.json).

## Технологии и конфигурация

| Часть проекта | Технологии / зависимости |
|---|---|
| Модель и обработка данных | Python 3.12, NumPy, pandas, scikit-learn; [requirements.txt](requirements.txt) |
| Агент, API, хранение | FastAPI, Pydantic, DuckDB, ecCodes; [pyproject.toml](backend/pyproject.toml), [uv.lock](backend/uv.lock) |
| Дашборд | Next.js 16, React 19, TypeScript, Tailwind, Three.js; [package-lock.json](package-lock.json) |
| Обучение | PyTorch 2.11.0+cu128; GPU используется при обучении MLP |

Backend читает `.env` в корне, затем `backend/.env`; переменные процесса
имеют приоритет. Образец — [.env.example](.env.example).

| Настройка | Назначение |
|---|---|
| `RENTBOX_SOURCE_TIMEZONE` | Часовой пояс CSV; в исследовательском запуске `Etc/GMT-5` |
| `RENTBOX_TIMESTAMP_MEANING` | Смысл метки; в исследовательском запуске `interval_start` |
| `RENTBOX_ALLOW_RESEARCH_TIME_SETTINGS` | `true` разрешает расчёт с явно неподтверждёнными настройками |
| `RENTBOX_TIME_CONFIGURATION_CONFIRMED` | По умолчанию `false`; менять после ответа организаторов |
| `RENTBOX_AGENT_FACTORY` | По умолчанию `src.agent:create_agent` |
| `RENTBOX_MODEL_DIR` | Основная модель — `artifacts/gfs-model`; можно задать другой каталог через окружение процесса |
| `RENTBOX_DATABASE_PATH` | `data/forecasts.duckdb`; в Docker — `/app/state/forecasts.duckdb` в сохраняемом томе |
| `RENTBOX_GFS_CACHE` | Изменяемый кэш: `data/gfs-runtime`; в Docker — `/app/state/gfs`. Задаётся окружением процесса |
| `RENTBOX_CORS_ORIGINS` | JSON-массив разрешённых адресов интерфейса |
| `BACKEND_PORT` / `WEB_PORT` | Порты API / интерфейса: обычно `8000` / `3000` |

Если `.env` уже существует и получена ошибка `CONFIGURATION_REQUIRED`,
проверьте первые четыре настройки. Для исследовательского запуска API
можно использовать `make demo`. Подтверждение других временных настроек
потребует согласовать их с обученной моделью.

## Известные ограничения

- Временные настройки исходных CSV ещё требуют подтверждения организаторов.
- Факта февраля и номинальной мощности турбин нет: метрики февраля
  и результаты в МВт/МВт·ч неизвестны. Модель выдаёт точечный прогноз;
  вероятностные интервалы пока не рассчитываются.
- Текущий сценарий NOAA рассчитан на ежедневный выпуск в 18:00 UTC.
  Погодная сетка 0.25° и интерполяция трёхчасовых опор ограничивают детализацию.
- Дашборд использует синтетические данные, в том числе демонстрационные метрики
  и полосу неопределённости. Они не показывают качество основной модели.
- DuckDB рассчитан на один процесс-писатель; backend запускается с одним worker.
- Основной сценарий NOAA выполнен через локальный API: 29/29 запусков.
  Чистую Docker-сборку после подключения NOAA ещё нужно повторить;
  проверки предыдущей версии описаны в [CHANGELOG](CHANGELOG.md).
- **Публичный деплой:** пока отсутствует. **Видео демо:** пока отсутствует.

## Где лежат данные, модель и документация

| Путь | Содержимое |
|---|---|
| `data/incoming/` | Два исходных CSV организаторов, история до 31 января 2026 |
| `data/gfs-runs/` | 730 погодных циклов с 1 марта 2024 по 28 февраля 2026 и их происхождение |
| `artifacts/gfs-model/` | Веса, январские метрики и прогнозы февраля |
| `artifacts/gfs-search/` | Протокол и результаты выбора 400 конфигураций |
| `src/agent.py`, `src/gfs_model.py` | Контроллер и расчёт мощности |
| `backend/app/`, `src/storage.py` | HTTP API и история прогнозов |
| `apps/web/`, `packages/ui/` | Интерфейс Windcast |

Дополнительно: [ТЗ и критерии](docs/hackathon/track-energy.md),
[план команды](docs/PLAN.md), [бэклог](docs/BACKLOG.md),
[backend](backend/README.md), [frontend](docs/FRONTEND.md),
[подключение интерфейса](docs/frontend-integration.md).

<details>
<summary><strong>Повторное обучение и команды разработчика</strong></summary>

Для повторного обучения нужны зависимости backend и PyTorch с CUDA.
Для готового прогноза обучение не требуется. Все команды — из корня проекта:

```bash
# Сохранённые циклы уже в git; загрузка недостающих требует сети и ecCodes.
python -m scripts.fetch_gfs_runs --start 2024-03-01 --end 2026-02-28
python -m scripts.train_gfs prepare
python -m scripts.train_gfs train --worker cpu
python -m scripts.train_gfs train --worker local-gpu
python -m scripts.train_gfs train --worker cloud-gpu
python -m scripts.train_gfs finalize
```

Имена GPU-workers обозначают разные наборы конфигураций, а не удалённый запуск.
Команды можно выполнить на одной GPU-машине. При работе на двух машинах перед
`finalize` объедините каталоги workers в `artifacts/gfs-search/`.
Протокол, периоды выбора и ограничения оценки — в [отчёте модели](artifacts/gfs-model/report.md).

Предыдущие эксперименты: `artifacts/ensemble/` и `artifacts/expanded/`.
`artifacts/power_curve/` — диагностика по фактическому ветру; её ошибку нельзя
использовать как качество прогноза на сутки.

Команды разработчика: `make dev`, `make openapi`, `make lint`, `make test`;
для frontend — `npm run build`, `npm run lint`, `npm run typecheck`, `npm test`.

</details>

## Внешние материалы

<details>
<summary>Источники данных, библиотеки и лицензии</summary>

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
| ESLint / Prettier | [ESLint](https://eslint.org/), [Prettier](https://prettier.io/) | MIT |
| pytest / Ruff | [pytest.org](https://docs.pytest.org/), [docs.astral.sh/ruff](https://docs.astral.sh/ruff/) | MIT |
| Three.js, просмотр 3D-турбины | [Three.js](https://threejs.org/) | MIT; версия и лицензия закреплены в package-lock.json |
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

3D-турбина создана командой в Blender; исходная сцена и генератор включены
в репозиторий. Blender и MCP использовались при создании сцены и не требуются
для запуска. Источники и ограничения иллюстрации — в [документации frontend](docs/FRONTEND.md).

</details>

## Заранее подготовленные компоненты

До реализации подготовлены организационная документация, служебные скрипты
и локальное Python/CUDA-окружение. Погодный модуль, модель, агент, backend
и интерфейс разрабатываются под кейс в этом репозитории 23.09.2026.
Для интерфейса использованы Next.js и компоненты shadcn/ui (Vega, Base UI).

## AI-инструменты и вклад участников

- **Codex:** данные, погода, обучение модели, агент, backend, контракт API и документация.
- **Claude Code:** DuckDB, аудит, дополнительные эксперименты обучения, скрипт запуска и интеграционные материалы.
- **Работа команды:** данные и модель, HTTP API, интерфейс и 3D-визуализация.
  Личный вклад участников подтверждается историей коммитов; именной список
  необходимо заполнить перед сдачей.
