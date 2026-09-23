# NVIDIA: обучение и API

В Windcast доступны два независимых способа работы с NVIDIA:

| Возможность | Как работает |
|---|---|
| Обучение прогнозной модели | PyTorch/CUDA на своей видеокарте или GPU NVIDIA Brev |
| Пояснения и рекомендации | HTTP-запросы к NVIDIA NIM по серверному API-ключу |

NIM предоставляет инференс готовых моделей. Ключ `build.nvidia.com` сам по себе
не запускает обучение нашей модели ВЭС: для обучения через API потребовался бы
отдельный сервис с обучающим заданием. Подробнее: [NIM](https://docs.api.nvidia.com/nim/docs/introduction)
и [NeMo Customizer](https://docs.nvidia.com/nemo-platform/documentation/customizer-reference).

Помощник сайта использует OpenAI GPT-6 Astra: [отдельная инструкция](AI-HELP.md).

## Обучение одной командой

Нужны Python 3.12 и зависимости `requirements.txt`; для нейросетей на GPU —
PyTorch с рабочей CUDA. Пакеты скрипт самостоятельно не устанавливает.

```bash
./scripts/train.sh --check
./scripts/train.sh --cpu
./scripts/train.sh --gpu
./scripts/train.sh --cloud
```

`--cpu` выбирает CPU-модели; `--gpu` требует доступной CUDA. Можно задать
интерпретатор: `PYTHON=/path/to/python ./scripts/train.sh --check`.

Новые результаты сохраняются в `artifacts/retraining/<дата-и-процесс>/`:
`search/` — отбор кандидатов, `model/` — веса, метрики и прогнозы.
Свой путь: `./scripts/train.sh --gpu --output artifacts/retraining/experiment-1`.
Завершается только выбранный набор моделей, поэтому CPU-запуск не ждёт результатов
двух GPU. Текущие веса `artifacts/gfs-model` автоматически не заменяются.
Новый каталог можно выбрать переменной процесса `RENTBOX_MODEL_DIR` после сравнения
результатов; в Docker для него нужно обеспечить копирование или монтирование.

Отбор остаётся на ноябре–декабре 2025. Январь — мониторинг, февраль — прогноз
без факта. Погода проходит прежние проверки доступности на `as_of`.

## API NVIDIA NIM

В существующем `.env` задайте `NVIDIA_API_KEY` и:

```dotenv
NVIDIA_ENABLED=true
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1.5
NVIDIA_TIMEOUT_SECONDS=20
```

Ключ остаётся на сервере. Для проверки из окружения с зависимостями backend:

```bash
./scripts/test-nvidia-api.sh
python -m scripts.nvidia_api training-advice
```

Вторая команда отправляет только конфигурации и метрики отбора ноября–декабря.
Для своего эксперимента добавьте `--selection artifacts/retraining/experiment-1/search/selection.json`.
Рекомендации не изменяют параметры и не запускают обучение.

После `./run.sh all` доступны:

- `GET /api/integrations/nvidia` — конфигурация без секретов;
- `POST /api/integrations/nvidia/check` — реальный проверочный запрос;
- `POST /api/agent/runs/{run_id}/explanation` — пояснение завершённого выпуска.

В NIM уходят агрегаты уже рассчитанной мощности. Числа прогноза, история и
исторический replay не зависят от ответа LLM. При отсутствии ключа или ошибке
пояснение возвращает исходный анализ контроллера с `provider=policy`.
CLI завершается с понятной ошибкой и ненулевым кодом, если API недоступен.
