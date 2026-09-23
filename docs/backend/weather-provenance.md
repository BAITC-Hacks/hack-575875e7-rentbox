# Происхождение погоды — контракт v0.3

Backend описывает источник каждого погодного входа, используемого для каждого
прогнозного часа. Публичная структура:

```text
series[].weather.sources[]              каталог погодных ответов
series[].points[].weather_inputs[]       ссылки на входы конкретного часа
```

Один объект sources соответствует одному ответу источника, например месячному
файлу GFS или ICON. source_id уникален внутри серии; предпочтителен стабильный
идентификатор вида gfs_global:2026-02. Дата месяца определяется по valid_time.
Каждый объявленный источник должен использоваться. В одном часу не допускается
повтор source_id или пары provider/model. Адаптер перечисляет все модели,
фактически участвующие в расчёте этого часа.

## Источник и ссылка на него

| Поле источника | Single Run | Previous Runs |
|---|---|---|
| product | single_run | previous_runs |
| source_id | Локальный идентификатор ответа | Локальный идентификатор ответа |
| provider, model | Поставщик и погодная модель | Поставщик и погодная модель |
| initialization_time | Известная дата конкретного выпуска | null |
| available_at | Дата доступности по метаданным источника | null |
| availability_basis | Обоснование доступности | previous_runs_offset_plus_12h_v1 |
| retrieved_at | Фактическое скачивание | Фактическое скачивание |
| sha256 | SHA-256 исходного ответа | SHA-256 исходного ответа |

Ссылка weather_inputs содержит source_id и:

- для Single Run: forecast_offset_days=null, available_at_estimate=null;
- для Previous Runs: forecast_offset_days — целое 1…7,
  available_at_estimate — обязательная дата с зоной.

Backend использует фиксированную политику v1:

```text
available_at_estimate = valid_time - forecast_offset_days * 24h + 12h
```

Вычисленное значение должно точно совпадать с переданным и быть не позже as_of.
Указывать другую политику или подставлять оценку в available_at запрещено схемой.
Для Single Run проверяются initialization_time <= available_at <= as_of
и available_at <= retrieved_at. Все даты приводятся к UTC.

Запас +12 часов — допущение проекта, не измеренная историческая задержка.
Backend добавляет об этом предупреждение в событие review, warnings задания
и analysis.warnings. Такая проверка не подтверждает фактическую публикацию
погодного выпуска в прошлом. Основание политики требуется подтвердить отдельно.

## Пример для двух моделей

Ниже фрагменты метаданных, а не готовый прогноз мощности. Времена скачивания
и SHA взяты из data/weather/{gfs_global,icon_global}/2026-02.meta.json.
Пример использует as_of=2026-01-31T18:00:00Z и valid_time=2026-02-01T06:00:00Z.

Каталог weather:

```json
{
  "sources": [
    {
      "source_id": "gfs_global:2026-02",
      "provider": "Open-Meteo",
      "model": "gfs_global",
      "product": "previous_runs",
      "initialization_time": null,
      "available_at": null,
      "availability_basis": "previous_runs_offset_plus_12h_v1",
      "retrieved_at": "2026-09-23T08:45:30.213890Z",
      "sha256": "3c2345b869df9a34015e6fcc09abcf86602ac6583701f34c22021045d20845d3"
    },
    {
      "source_id": "icon_global:2026-02",
      "provider": "Open-Meteo",
      "model": "icon_global",
      "product": "previous_runs",
      "initialization_time": null,
      "available_at": null,
      "availability_basis": "previous_runs_offset_plus_12h_v1",
      "retrieved_at": "2026-09-23T08:45:30.863766Z",
      "sha256": "062738c71bc232f19560c10764a31733206b551de6ba00716ea6869b2a6c8247"
    }
  ]
}
```

Ссылки weather_inputs у этого прогнозного часа:

```json
[
  {
    "source_id": "gfs_global:2026-02",
    "forecast_offset_days": 1,
    "available_at_estimate": "2026-01-31T18:00:00Z"
  },
  {
    "source_id": "icon_global:2026-02",
    "forecast_offset_days": 1,
    "available_at_estimate": "2026-01-31T18:00:00Z"
  }
]
```

Для следующего часа 07:00 с offset=1 оценка стала бы 19:00 и вышла за as_of.
Нужен выбранный модулем погоды более ранний допустимый offset, например 2.
Backend не заменяет offset сам и не придумывает новые погодные значения.

## Что передаёт модуль коллеги

| Откуда | Поле API / действие |
|---|---|
| src.weather.load_archive | Проверка хешей кеша и получение исходных рядов |
| select_as_of(...), valid_time | points[].valid_time |
| forecast_offset_days выбранной строки | weather_inputs[].forecast_offset_days |
| available_at_upper_bound выбранной строки | weather_inputs[].available_at_estimate |
| meta.json: provider/model/retrieved_at/sha256 | Поля источника в weather.sources |
| Название продукта кеша | product=previous_runs; свободный текст из meta.json не копировать |
| PUBLICATION_MARGIN_HOURS=12 | availability_basis=previous_runs_offset_plus_12h_v1 |
| Погодные модели, используемые моделью мощности | По ссылке на каждую в weather_inputs |

Backend сверяет арифметику оценки и ограничения времени. Он не скачивает погодный
кеш и не проверяет его байты: это делает load_archive в модуле погоды. Проверка
формата SHA в API не заменяет проверку целостности файла.

У таблицы, возвращённой select_as_of, один offset применяется к столбцам GFS/ICON.
В адаптере этот offset передаётся отдельно для каждой используемой модели.
Если горизонт пересекает границу месяца, добавляются ссылки на оба месячных файла.
Хеш входов input_sha256 включает погодные SHA, offsets, версию политики и её
параметры. Время скачивания и локальные имена source_id не должны менять расчёт.

## Что показывает фронт

- Для previous_runs: «Архив Previous Runs», модели и offset по выбранному часу.
- Для available_at_estimate: «Оценка доступности по политике +12 ч».
- Для неизвестных initialization_time/available_at: «Источник не сообщает».
- Для retrieved_at: «Архив загружен». Эта дата не обозначает историческую публикацию.
- Предупреждения из analysis.warnings показываются вместе с прогнозом.

Интерпретировать null как дату 1970 года или as_of нельзя.

## CSV, DuckDB и прежние ответы

CSV сохраняет одну строку на турбину/час. Новая колонка weather_inputs_json
содержит JSON-массив раскрытых ссылок: поля источника плюс offset/оценка.
При наличии оценки weather_available_at пуст; weather_available_at_estimate —
максимум точных и оценочных дат всех входов этого часа. Без оценок
weather_available_at — максимум точных дат, колонка оценки пуста.
weather_initialization_time заполняется только при одном источнике Single Run.

В DuckDB прежние таблицы ForecastStore сохраняются. Для Previous Runs и набора
источников weather_run=NULL, полное происхождение хранится в api_runs.result.
В note записи ForecastStore добавляется связь с API run_id.

Ранее сохранённый JSON с одиночным weather читается через адаптер совместимости.
Он получает source_id=legacy_<sha256> и ссылки у всех точек; исходная запись
в базе не переписывается. Выход API всегда использует sources/weather_inputs.
Новые интеграции должны формировать v0.3. При сравнении одинакового input_sha256
учитывается содержимое источников и их привязка к часам; время повторного
скачивания, порядок списка и локальные source_id игнорируются.

Источники семантики:
[Previous Runs](https://open-meteo.com/en/docs/previous-runs-api),
[Single Runs](https://open-meteo.com/en/docs/single-runs-api).
