#!/usr/bin/env bash
# Запуск RentBox одной командой.
#
#   ./run.sh          поднять сервис и показать, что делать дальше
#   ./run.sh all      поднять backend и дашборд вместе
#   ./run.sh demo     поднять и сразу посчитать прогноз на 48 часов
#   ./run.sh check    только проверить окружение, ничего не запускать
#   ./run.sh stop     остановить
#   ./run.sh logs     показать журнал сервиса
#
# Ключи и внешние учётные записи не нужны: прогнозы погоды лежат в репозитории
# (data/weather), модель — в artifacts. Достаточно Docker; если его нет,
# скрипт поднимет сервис локально через uv.

set -euo pipefail

cd "$(dirname "$0")"

PORT="${BACKEND_PORT:-8000}"
COMPOSE=""
MODE=""

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '  %s\n' "$*"; }

die() {
    red "Ошибка: $1"
    [ $# -gt 1 ] && printf '\n%s\n' "$2"
    exit 1
}

# --- окружение --------------------------------------------------------------

detect_compose() {
    if docker compose version >/dev/null 2>&1; then
        COMPOSE="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE="docker-compose"
    fi
}

port_free() {
    ! (command -v curl >/dev/null 2>&1 && curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$1/api/health") 2>/dev/null
}

pick_port() {
    local candidate="$PORT"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if port_free "$candidate"; then
            PORT="$candidate"
            return 0
        fi
        candidate=$((candidate + 1))
    done
    die "порты $PORT..$candidate заняты" "Освободите порт или задайте свой: BACKEND_PORT=9000 ./run.sh"
}

check() {
    bold "Проверка окружения"
    local ready=1

    detect_compose
    if [ -n "$COMPOSE" ] && docker info >/dev/null 2>&1; then
        green "  ✓ Docker готов — запуск в контейнере"
        MODE="docker"
    elif [ -n "$COMPOSE" ]; then
        info "  ⚠ Docker установлен, но демон не отвечает. Запустите Docker Desktop."
    else
        info "  · Docker не найден"
    fi

    if [ -z "$MODE" ]; then
        if command -v uv >/dev/null 2>&1 || [ -x .tools/bin/uv ]; then
            green "  ✓ uv найден — локальный запуск"
            MODE="local"
        else
            red "  ✗ нет ни рабочего Docker, ни uv"
            ready=0
        fi
    fi

    for path in data/incoming/turbine_1.csv data/incoming/turbine_2.csv; do
        if [ -f "$path" ]; then
            green "  ✓ $path"
        else
            red "  ✗ нет $path"
            ready=0
        fi
    done

    local months
    months=$(find data/weather -name '*.json' 2>/dev/null | grep -c . || true)
    if [ "$months" -gt 0 ]; then
        green "  ✓ кэш прогнозов погоды: $months файлов (интернет не нужен)"
    else
        red "  ✗ нет кэша погоды в data/weather"
        ready=0
    fi

    [ "$ready" -eq 1 ] || die "окружение не готово" "Проверьте пункты со знаком ✗ выше."
}

# --- конфигурация -----------------------------------------------------------

ensure_env() {
    [ -f .env ] && return 0

    bold "Создаю .env"
    cp .env.example .env
    cat >> .env <<'SETTINGS'

# Настройки времени исходных измерений. ИССЛЕДОВАТЕЛЬСКОЕ ДОПУЩЕНИЕ:
# организаторы их не подтверждали. Метки CSV считаются началом
# десятиминутного интервала в UTC+5. Все результаты помечены как research.
RENTBOX_SOURCE_TIMEZONE=Etc/GMT-5
RENTBOX_TIMESTAMP_MEANING=interval_start
RENTBOX_ALLOW_RESEARCH_TIME_SETTINGS=true
SETTINGS
    info "Без этих настроек сервис поднимется, но расчёт вернёт CONFIGURATION_REQUIRED."
    info "Когда организаторы подтвердят время — поправьте .env и уберите allow_research."
}

# --- запуск -----------------------------------------------------------------

wait_healthy() {
    local url="http://127.0.0.1:$PORT/api/health"
    printf '  ожидаю готовности'
    for _ in $(seq 1 60); do
        if curl -s --max-time 2 "$url" >/dev/null 2>&1; then
            printf '\n'
            green "  ✓ сервис отвечает"
            return 0
        fi
        printf '.'
        sleep 2
    done
    printf '\n'
    die "сервис не ответил за 120 секунд" "Журнал: ./run.sh logs"
}

start_docker() {
    bold "Запуск в Docker (порт $PORT)"
    BACKEND_PORT="$PORT" $COMPOSE up -d --build --wait 2>&1 | grep -Ev '^#|DONE|CACHED' || true
    wait_healthy
}

start_local() {
    bold "Локальный запуск (порт $PORT)"
    local uv_bin="uv"
    [ -x .tools/bin/uv ] && uv_bin=".tools/bin/uv"
    info "устанавливаю зависимости…"
    UV_CACHE_DIR="$PWD/.tools/uv-cache" UV_PYTHON_INSTALL_DIR="$PWD/.tools/python" \
        "$uv_bin" sync --project backend --frozen >/dev/null
    # Settings reads .env as dotenv; sourcing it as shell would corrupt JSON values.
    mkdir -p .run
    backend/.venv/bin/uvicorn src.api:app --host 127.0.0.1 --port "$PORT" \
        > .run/backend.log 2>&1 &
    echo $! > .run/backend.pid
    wait_healthy
}

start() {
    check
    ensure_env
    pick_port
    if [ "$MODE" = "docker" ]; then start_docker; else start_local; fi

    printf '\n'
    bold "Готово"
    info "API:            http://127.0.0.1:$PORT/api/health"
    info "Документация:   http://127.0.0.1:$PORT/docs"
    info "Прогноз:        ./run.sh demo"
    info "Остановить:     ./run.sh stop"
}

# --- демонстрация -----------------------------------------------------------

demo() {
    local base="http://127.0.0.1:$PORT"
    curl -s --max-time 3 "$base/api/health" >/dev/null 2>&1 || start

    printf '\n'
    bold "Расчёт прогноза на 48 часов, момент решения 2026-01-31 18:00 UTC"
    local response run_id status
    response=$(curl -s -X POST "$base/api/agent/runs" \
        -H 'Content-Type: application/json' \
        -d '{"as_of":"2026-01-31T18:00:00Z","horizon_hours":48,"turbine_ids":[1,2]}')
    run_id=$(printf '%s' "$response" | sed -n 's/.*"run_id":"\([^"]*\)".*/\1/p')

    if [ -z "$run_id" ]; then
        red "  не удалось запустить расчёт"
        printf '  %s\n' "$response"
        exit 1
    fi
    info "запуск $run_id"

    for _ in $(seq 1 60); do
        status=$(curl -s "$base/api/agent/runs/$run_id" \
                 | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')
        case "$status" in
            completed|succeeded) break ;;
            failed|error) die "расчёт завершился с ошибкой" "Подробности: $base/api/agent/runs/$run_id" ;;
        esac
        printf '.'
        sleep 2
    done
    printf '\n'

    mkdir -p artifacts
    curl -s "$base/api/agent/runs/$run_id/forecast.csv" -o artifacts/demo-forecast.csv
    local rows
    rows=$(($(wc -l < artifacts/demo-forecast.csv) - 1))
    green "  ✓ получено $rows почасовых значений → artifacts/demo-forecast.csv"

    printf '\n'
    bold "Первые строки"
    cut -d, -f3,4,5,6 artifacts/demo-forecast.csv | head -5 | sed 's/^/  /'
    printf '\n'
    info "Полный прогноз февраля: artifacts/gfs-model/february_replay.csv"
    info "Метрики и ограничения:  artifacts/gfs-model/report.md"
}

# --- дашборд ----------------------------------------------------------------

WEB_PORT="${WEB_PORT:-3000}"

start_web() {
    command -v npm >/dev/null 2>&1 || die "нужен Node.js 20+" "Скачать: https://nodejs.org"

    if [ ! -d node_modules ]; then
        bold "Ставлю зависимости дашборда (один раз, несколько минут)"
        npm install --no-audit --no-fund >/dev/null
    fi

    bold "Запуск дашборда (порт $WEB_PORT)"
    mkdir -p .run
    # Адрес backend передаётся фронту; CORS на бэке уже разрешает localhost:3000.
    NEXT_PUBLIC_API_URL="http://127.0.0.1:$PORT/api" \
        npm run dev --workspace web -- --port "$WEB_PORT" > .run/web.log 2>&1 &
    echo $! > .run/web.pid

    printf '  ожидаю дашборд'
    for _ in $(seq 1 45); do
        if curl -s --max-time 2 -o /dev/null "http://127.0.0.1:$WEB_PORT"; then
            printf '\n'
            green "  ✓ дашборд отвечает"
            return 0
        fi
        printf '.'
        sleep 2
    done
    printf '\n'
    die "дашборд не поднялся за 90 секунд" "Журнал: tail -50 .run/web.log"
}

all() {
    start
    printf '\n'
    start_web
    printf '\n'
    bold "Оба сервиса подняты"
    info "Дашборд:        http://127.0.0.1:$WEB_PORT"
    info "API:            http://127.0.0.1:$PORT/api"
    info "Документация:   http://127.0.0.1:$PORT/docs"
    info "Остановить:     ./run.sh stop"
}

# --- остановка --------------------------------------------------------------

stop() {
    detect_compose
    if [ -n "$COMPOSE" ] && docker info >/dev/null 2>&1; then
        $COMPOSE down 2>/dev/null || true
    fi
    for name in backend web; do
        if [ -f ".run/$name.pid" ]; then
            kill "$(cat ".run/$name.pid")" 2>/dev/null || true
            rm -f ".run/$name.pid"
        fi
    done
    green "Остановлено"
}

logs() {
    detect_compose
    if [ -f .run/backend.log ]; then
        tail -50 .run/backend.log
    elif [ -n "$COMPOSE" ]; then
        $COMPOSE logs --tail 50
    else
        die "журнал не найден"
    fi
}

case "${1:-start}" in
    start) start ;;
    all)   all ;;
    demo)  demo ;;
    check) check; green "Окружение готово, режим: $MODE" ;;
    stop)  stop ;;
    logs)  logs ;;
    *)     die "неизвестная команда: $1" "Доступно: start, all, demo, check, stop, logs" ;;
esac
