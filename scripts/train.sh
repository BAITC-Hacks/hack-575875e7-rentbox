#!/usr/bin/env bash
# Переобучение модели с автоматическим выбором устройства.
#
#   ./scripts/train.sh            найти NVIDIA и обучить на ней, иначе на CPU
#   ./scripts/train.sh --cpu      принудительно на CPU
#   ./scripts/train.sh --gpu      требовать доступную CUDA
#   ./scripts/train.sh --check    только показать, что будет использовано
#   ./scripts/train.sh --cloud    подсказка по запуску на NVIDIA Brev
#   ./scripts/train.sh --output DIR  каталог новых результатов
#
# Своё окружение с PyTorch: PYTHON=/path/to/python ./scripts/train.sh
#
# Для готового прогноза обучение не нужно: модель лежит в artifacts/gfs-model
# и считается на CPU без PyTorch. Этот скрипт нужен, только чтобы обучить заново.

set -euo pipefail
cd "$(dirname "$0")/.."

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '  %s\n' "$*"; }

PYTHON="${PYTHON:-}"
WORKER=""
FORCE_CPU=0
FORCE_GPU=0
CHECK_ONLY=0
CLOUD_HINT=0
OUTPUT_DIR=""

die() { red "$*"; exit 1; }

find_python() {
    # Готовое окружение можно указать явно: PYTHON=/path/to/python ./scripts/train.sh
    if [ -n "$PYTHON" ]; then
        command -v "$PYTHON" >/dev/null 2>&1 || [ -x "$PYTHON" ] || die "Не найден указанный PYTHON: $PYTHON"
        return 0
    fi
    for candidate in .venv/bin/python ../.venv/bin/python backend/.venv/bin/python python3.12 python3; do
        if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
            if "$candidate" -c 'import sys; assert sys.version_info >= (3, 12); import numpy, pandas, sklearn, pyarrow, httpx, duckdb, joblib' >/dev/null 2>&1; then
                PYTHON="$candidate"
                return 0
            fi
        fi
    done
    red "Не найден Python 3.12."
    info "Установите зависимости: make setup"
    exit 1
}

# Что доступно: GPU, только CPU, или PyTorch вовсе не установлен.
detect_device() {
    find_python
    "$PYTHON" -c 'import sys; assert sys.version_info >= (3, 12), "нужен Python 3.12+"; import numpy, pandas, sklearn, pyarrow, httpx, duckdb, joblib' \
        || die "В выбранном Python отсутствуют зависимости обучения. Используйте requirements.txt и Python 3.12+."
    info "Python: $PYTHON"
    local report
    report=$("$PYTHON" - <<'PROBE' 2>/dev/null || true
try:
    import torch
except ImportError:
    print("no-torch")
else:
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        total = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"cuda\t{name}\t{total:.1f}")
    else:
        print("cpu-only")
PROBE
)
    case "${report%%$'\t'*}" in
        cuda)
            local name memory
            name=$(printf '%s' "$report" | cut -f2)
            memory=$(printf '%s' "$report" | cut -f3)
            green "  ✓ NVIDIA найдена: $name, ${memory} ГБ"
            WORKER="local-gpu"
            ;;
        cpu-only)
            info "  · PyTorch есть, но CUDA недоступна — обучение пойдёт на CPU"
            WORKER="cpu"
            ;;
        no-torch)
            info "  · PyTorch не установлен — доступно обучение только на CPU"
            info "    Для GPU: uv pip install --python $PYTHON 'torch==2.11.0' \\"
            info "             --index-url https://download.pytorch.org/whl/cu128"
            WORKER="cpu"
            ;;
        *)
            info "  · Не удалось определить устройство, выбран CPU"
            WORKER="cpu"
            ;;
    esac
    if [ "$FORCE_CPU" -eq 1 ]; then
        WORKER="cpu"
        info "  · Принудительный режим CPU"
    fi
    if [ "$FORCE_GPU" -eq 1 ] && [ "$WORKER" != "local-gpu" ]; then
        die "Запрошена GPU, но CUDA в выбранном Python недоступна."
    fi
    return 0
}

cloud_hint() {
    bold "Обучение на NVIDIA Brev"
    cat <<'TEXT'
  Облачная GPU нужна, только чтобы перебрать больше конфигураций.
  Результат обучения — те же NumPy-веса, инференс остаётся на CPU.

  1. Активировать промокод Brev и создать инстанс с GPU.
  2. Использовать этот же репозиторий с data/incoming и data/gfs-runs.
     В Python должны быть зависимости requirements.txt и PyTorch с CUDA.
  3. Запустить на инстансе:
       PYTHON=.venv/bin/python ./scripts/train.sh --gpu --output artifacts/retraining/brev
  4. Забрать каталог artifacts/retraining/brev/model обратно на рабочую машину.

  --gpu проверяет CUDA до обучения. Готовая конкурсная модель сохраняется.
  Ключ build.nvidia.com используется для вызовов NIM; этот скрипт обучает
  модель на GPU инстанса и не отправляет обучение в NIM API.
TEXT
}

while [ $# -gt 0 ]; do
    case "$1" in
        --cpu)   FORCE_CPU=1 ;;
        --gpu)   FORCE_GPU=1 ;;
        --check) CHECK_ONLY=1 ;;
        --cloud) CLOUD_HINT=1 ;;
        --output) [ $# -ge 2 ] || die "После --output нужен каталог"; OUTPUT_DIR="$2"; shift ;;
        -h|--help) sed -n '2,11p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) die "Неизвестный аргумент: $1" ;;
    esac
    shift
done
[ "$FORCE_CPU" -eq 0 ] || [ "$FORCE_GPU" -eq 0 ] || die "Выберите один режим: --cpu или --gpu"
if [ "$CLOUD_HINT" -eq 1 ]; then cloud_hint; exit 0; fi

bold "Подготовка к обучению"
detect_device
if [ "$CHECK_ONLY" -eq 1 ]; then green "Будет использовано: $WORKER"; exit 0; fi
printf '\n'

if [ "$WORKER" = "cpu" ]; then
    info "Будут обучены CPU-модели; PyTorch и NVIDIA API для этого режима не нужны."
fi
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/retraining/$(date -u +%Y%m%dT%H%M%SZ)-$$}"
SEARCH_DIR="$OUTPUT_DIR/search"
MODEL_DIR="$OUTPUT_DIR/model"
info "Новые результаты: $OUTPUT_DIR"

bold "Подготовка обучающей выборки"
"$PYTHON" -m scripts.train_gfs prepare --search-dir "$SEARCH_DIR"

printf '\n'
bold "Обучение, воркер $WORKER"
"$PYTHON" -m scripts.train_gfs train --worker "$WORKER" --search-dir "$SEARCH_DIR"

printf '\n'
bold "Отбор модели и январская оценка"
"$PYTHON" -m scripts.train_gfs finalize --workers "$WORKER" --search-dir "$SEARCH_DIR" --output-dir "$MODEL_DIR"

printf '\n'
green "Готово. Модель и метрики — в $MODEL_DIR/"
info "Январская оценка: $MODEL_DIR/metrics.json"
info "Прогноз февраля: $MODEL_DIR/february_replay.csv"
info "Рабочая модель artifacts/gfs-model сохраняется; новый результат можно выбрать через RENTBOX_MODEL_DIR."
