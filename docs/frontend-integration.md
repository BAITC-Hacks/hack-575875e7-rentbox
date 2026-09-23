# Подключение дашборда к backend

Для того, кто сводит фронт и бэк. Контракт целиком — [API.md](API.md) и
[backend/openapi.json](../backend/openapi.json); здесь — что где лежит, чего в API нет,
и живые примеры ответов.

## Поднять оба сервиса

```bash
./run.sh all
```

Backend на `:8000`, дашборд на `:3000`. Если порт занят, скрипт берёт следующий свободный
и печатает фактические адреса. Задать явно: `BACKEND_PORT=8000 WEB_PORT=3000 ./run.sh all`.
Остановить: `./run.sh stop`. Журналы: `.run/backend.log`, `.run/web.log`.

CORS на бэкенде уже разрешает `http://localhost:3000` и `http://localhost:5173`
(`RENTBOX_CORS_ORIGINS` в `.env`). Адрес API прилетает во фронт как `NEXT_PUBLIC_API_URL`.

## Что готово с какой стороны

| Сторона | Состояние |
|---|---|
| Backend | 9 маршрутов работают, контракт v0.3, агент считает прогноз и пишет в DuckDB |
| Дашборд | вся вёрстка готова, `apps/web/components/wind-dashboard.tsx` (1724 строки) |
| Связь | **нет ни одного вызова API** — данные берутся из `apps/web/lib/forecast-data.ts` |

Задача сводится к замене синтетики на вызовы. Вёрстку менять почти не придётся, кроме мест
из раздела «Чего в API нет».

## Маршруты

| Метод | Путь | Зачем дашборду |
|---|---|---|
| GET | `/api/health` | индикатор состояния, `research_mode`, `time_configuration_ready` |
| GET | `/api/turbines` | список турбин, координаты, ссылки на карту |
| GET | `/api/data/summary` | сводка по данным, покрытие, предупреждения |
| POST | `/api/agent/runs` | запустить расчёт, вернёт `run_id` |
| GET | `/api/agent/runs/{id}` | статус, стадия, прогресс, журнал событий |
| GET | `/api/agent/runs/{id}/forecast` | сам прогноз с происхождением данных |
| GET | `/api/agent/runs/{id}/forecast.csv` | то же в CSV, для кнопки «скачать» |
| POST | `/api/agent/replays` | прогон нескольких суток подряд |
| GET | `/api/agent/replays/{id}` | статус прогона |

## Сценарий одного расчёта

```ts
const api = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000/api"

// 1. запустить
const { run_id } = await fetch(`${api}/agent/runs`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    as_of: "2026-01-31T18:00:00Z",   // момент решения, не «сейчас»
    horizon_hours: 48,               // 24 или 48
    turbine_ids: [1, 2],
  }),
}).then(r => r.json())

// 2. опрашивать статус, пока не completed
//    в ответе есть stage, progress и events[] — это готовый журнал для UI
let run
do {
  await new Promise(r => setTimeout(r, 1500))
  run = await fetch(`${api}/agent/runs/${run_id}`).then(r => r.json())
} while (run.status === "queued" || run.status === "running")

// 3. забрать прогноз
const forecast = await fetch(`${api}/agent/runs/${run_id}/forecast`).then(r => r.json())
```

Расчёт занимает 1–3 секунды. Интервал опроса 1.5 с достаточен; поле `progress` (0…1)
и `stage` (`validate` → `weather` → `prepare` → `model` → `analyse` → `save`) можно
показывать прогресс-баром, а `events[]` — лентой шагов агента.

## Форма ответа `/forecast`

```json
{
  "run_id": "run_749ae327…",
  "as_of": "2026-01-31T18:00:00Z",
  "horizon_hours": 48,
  "unit": "normalized_power",
  "model_version": "2064702f58f0…",
  "training_data_available_until": "2026-01-30T19:00:00Z",
  "series": [
    {
      "turbine_id": 1,
      "points": [
        { "valid_time": "2026-01-31T19:00:00Z", "lead_hour": 1, "predicted_power": 0.0517 }
      ],
      "weather": { "sources": [ … ] },
      "storage_run_id": 1
    }
  ],
  "analysis": {
    "summary": "Прогноз на 48 ч для 2 турбин: мощность 0.020–0.962.",
    "warnings": [ … ]
  }
}
```

`analysis.warnings` — готовый текст для баннера. Оттуда, в частности, приходят
«Расхождение GFS/ICON по ветру достигает 9.2 м/с» и «Прогнозируется изменение мощности
до 0.57 за час» — это содержательные предупреждения, их стоит показывать, а не скрывать.

Полные примеры ответов лежат в [samples/](samples/), снятые с работающего сервиса:

| Файл | Что внутри |
|---|---|
| `samples/health.json` | состояние сервиса |
| `samples/turbines.json` | обе турбины с координатами |
| `samples/data-summary.json` | сводка данных и предупреждения |
| `samples/agent-run.json` | завершённый запуск со всеми событиями |
| `samples/agent-forecast.json` | прогноз на 48 ч по двум турбинам, 80 КБ |

Их удобно подложить как фикстуры, пока идёт вёрстка.

## Чего в API нет, а на дашборде есть

Тип `ForecastPoint` в `apps/web/lib/forecast-data.ts` ожидает больше полей, чем отдаёт backend:

| Поле фронта | Есть в API? | Что делать |
|---|---|---|
| `forecast` | да — `predicted_power` | переименовать при разборе ответа |
| `timestamp` | да — `valid_time` | `hour` и `date` считать на фронте |
| `actual` | **нет** | фактических значений февраля не существует, данные обрываются 31.01. Для января факт можно взять из `artifacts/ensemble/january_predictions.csv`. На февральских графиках линию факта не рисовать |
| `lower`, `upper` | **нет** | интервал неопределённости не реализован (пункт 2.2 в [BACKLOG.md](BACKLOG.md)). Либо убрать полосу из графика, либо дождаться квантильной модели |
| `wind`, `temperature` | частично | лежат внутри `series[].weather`, не в точках. Если нужны на графике — уточнить у бэкенда, выносить ли их в `points[]` |

**Это обсудить до вёрстки графика:** три поля из девяти не приходят, и два из них
(`lower`/`upper`, `actual`) влияют на вид основного графика.

## Ошибки

Единый формат, коды понятные:

```json
{ "error": { "code": "CONFIGURATION_REQUIRED", "message": "…", "retryable": false } }
```

| Код | Когда | Что показать |
|---|---|---|
| `CONFIGURATION_REQUIRED` | не заданы настройки времени в `.env` | «сервис не настроен», подсказать `./run.sh` |
| `DATA_QUALITY_ERROR` | CSV не совпадает с отчётом аудита | «данные изменились, нужен повторный аудит» |
| `HTTP_404` | неизвестный `run_id` | «расчёт не найден» |

Поле `retryable` говорит, имеет ли смысл кнопка «повторить».

## Что учесть

- **`as_of` — это симулируемый момент решения**, а не текущее время. По условию задачи
  прогноз воспроизводится так, как если бы считался в прошлом. Дефолт для демо —
  `2026-01-31T18:00:00Z`; подставлять `new Date()` нельзя, погоды на сегодня в архиве нет.
- **Мощность нормализована в `[0, 1]`**, не МВт. Подписи осей — в долях номинала или процентах.
- **Повторный запуск с теми же параметрами** вернёт `reused_run_id` вместо нового расчёта.
  При обновлении погоды появится `revision` больше 1 и `supersedes_run_id`.
- **`research_mode: true` в `/api/health`** означает, что настройки времени не подтверждены
  организаторами. Это стоит показывать плашкой — результаты помечены как исследовательские.
