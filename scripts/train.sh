#!/usr/bin/env bash
# Переобучение модели с автоматическим выбором устройства.
#
#   ./scripts/train.sh            найти NVIDIA и обучить на ней, иначе на CPU
#   ./scripts/train.sh --cpu      принудительно на CPU
#   ./scripts/train.sh --check    только показать, что будет использовано
#   ./scripts/train.sh --cloud    подсказка по запуску на NVIDIA Brev
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

find_python() {
    # Готовое окружение можно указать явно: PYTHON=/path/to/python ./scripts/train.sh
    if [ -n "${PYTHON:-}" ] && [ -x "${PYTHON}" ]; then
        return 0
    fi
    for candidate in backend/.venv/bin/python .venv/bin/python python3.12 python3; do
        if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
            PYTHON="$candidate"
            return 0
        fi
    done
    red "Не найден Python 3.12."
    info "Установите зависимости: make setup"
    exit 1
}

# Что доступно: GPU, только CPU, или PyTorch вовсе не установлен.
detect_device() {
    find_python
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
    [ "$FORCE_CPU" -eq 1 ] && WORKER="cpu" && info "  · Принудительный режим CPU"
    return 0
}

cloud_hint() {
    bold "Обучение на NVIDIA Brev"
    cat <<'TEXT'
  Облачная GPU нужна, только чтобы перебрать больше конфигураций.
  Результат обучения — те же NumPy-веса, инференс остаётся на CPU.

  1. Активировать промокод Brev и создать инстанс с GPU.
  2. Скопировать пакет обучения и uv на инстанс:
       scp artifacts/brev-training.tar.gz <instance>:/tmp/
       scp $(command -v uv) <instance>:/tmp/wind-uv
  3. Запустить на инстансе: bash scripts/brev-train.sh
  4. Забрать artifacts/search/cloud-gpu/ обратно в репозиторий
     и выполнить: python -m scripts.train_gfs finalize

  Скрипт на инстансе откажется работать, если CUDA недоступна:
  тихого отката на CPU в облаке быть не должно.
TEXT
}

for argument in "$@"; do
    case "$argument" in
        --cpu)   FORCE_CPU=1 ;;
        --check) bold "Проверка устройства"; detect_device; green "Будет использовано: $WORKER"; exit 0 ;;
        --cloud) cloud_hint; exit 0 ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) red "Неизвестный аргумент: $argument"; exit 1 ;;
    esac
done

bold "Подготовка к обучению"
detect_device
printf '\n'

if [ "$WORKER" = "cpu" ]; then
    info "Обучение на CPU занимает заметно больше времени, чем на GPU."
    info "Готовая модель уже есть в artifacts/gfs-model — переобучение не обязательно."
    printf '  Продолжить? [y/N]: '
    read -r answer
    case "$answer" in
        y|Y|д|Д) ;;
        *) info "Отменено."; exit 0 ;;
    esac
    printf '\n'
fi

bold "Подготовка обучающей выборки"
"$PYTHON" -m scripts.train_gfs prepare

printf '\n'
bold "Обучение, воркер $WORKER"
"$PYTHON" -m scripts.train_gfs train --worker "$WORKER"

printf '\n'
bold "Отбор модели и январская оценка"
"$PYTHON" -m scripts.train_gfs finalize

printf '\n'
green "Готово. Модель и метрики — в artifacts/gfs-model/"
info "Отчёт: artifacts/gfs-model/report.md"
info "Проверить прогноз: ./run.sh demo"
