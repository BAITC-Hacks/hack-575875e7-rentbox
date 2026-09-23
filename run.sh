#!/usr/bin/env bash
# Запуск RentBox одной командой.
#
#   ./run.sh          меню выбора (или сразу запуск, если терминал неинтерактивный)
#   ./run.sh all      поднять backend и дашборд вместе
#   ./run.sh demo     поднять и сразу посчитать прогноз на 48 часов
#   ./run.sh check    только проверить окружение, ничего не запускать
#   ./run.sh stop     остановить
#   ./run.sh logs     показать журнал сервиса
#
# Ключи и внешние учётные записи не нужны: прогнозы погоды лежат в репозитории
# (data/gfs-runs), модель — в artifacts. Достаточно Docker; если его нет,
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
    # Занятым считается любой слушающий порт, а не только наш сервис:
    # иначе чужой процесс на этом порту обнаружится лишь при старте контейнера.
    ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
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
        if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
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
    local output
    local result=0
    output=$(BACKEND_PORT="$PORT" $COMPOSE up -d --build --wait 2>&1) || result=$?
    printf '%s\n' "$output" | grep -Ev '^#|DONE|CACHED|^$' || true

    # В WSL порт может держать процесс Windows: из Linux он не виден как
    # слушающий, поэтому ошибка всплывает только здесь. Сообщаем сразу,
    # вместо двух минут ожидания health.
    if printf '%s' "$output" | grep -q 'ports are not available\|address already in use\|port is already allocated'; then
        die "порт $PORT занят другим процессом" \
            "Попробуйте другой порт: BACKEND_PORT=$((PORT + 100)) ./run.sh"
    fi
    if [ "$result" -ne 0 ]; then
        $COMPOSE logs --tail 40 backend 2>&1 || true
        die "Docker не смог запустить backend" "Подробности ошибки приведены выше."
    fi
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
    # Повторный запуск использует порт контейнера этого Compose-проекта.
    # Иначе каждый ./run.sh all пересоздавал его на следующем порту.
    local published=""
    if [ "$MODE" = "docker" ]; then
        published=$($COMPOSE port backend 8000 2>/dev/null || true)
        published="${published##*:}"
    fi
    if [[ "$published" =~ ^[0-9]+$ ]] && { [ -z "${BACKEND_PORT:-}" ] || [ "$PORT" = "$published" ]; }; then
        PORT="$published"
    else
        pick_port
    fi
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
    start
    # start может выбрать свободный порт; адрес строится после его выбора.
    local base="http://127.0.0.1:$PORT"

    printf '\n'
    bold "Расчёт прогноза на 48 часов, момент решения 2026-01-31 18:00 UTC"
    local response run_id status
    response=$(curl --fail-with-body -sS --max-time 30 -X POST "$base/api/agent/runs" \
        -H 'Content-Type: application/json' \
        -d '{"as_of":"2026-01-31T18:00:00Z","horizon_hours":48,"turbine_ids":[1,2]}') \
        || die "не удалось запустить расчёт" "$response"
    run_id=$(printf '%s' "$response" | sed -n 's/.*"run_id":"\([^"]*\)".*/\1/p')

    if [ -z "$run_id" ]; then
        red "  не удалось запустить расчёт"
        printf '  %s\n' "$response"
        exit 1
    fi
    info "запуск $run_id"

    for _ in $(seq 1 60); do
        status=$(curl -fsS --max-time 10 "$base/api/agent/runs/$run_id" \
                 | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')
        case "$status" in
            completed|succeeded) break ;;
            failed|error) die "расчёт завершился с ошибкой" "Подробности: $base/api/agent/runs/$run_id" ;;
        esac
        printf '.'
        sleep 2
    done
    printf '\n'
    case "$status" in
        completed|succeeded) ;;
        *) die "расчёт ещё не завершён" "Состояние: $base/api/agent/runs/$run_id" ;;
    esac

    mkdir -p artifacts
    curl -fsS --max-time 30 "$base/api/agent/runs/$run_id/forecast.csv" -o artifacts/demo-forecast.csv
    local rows
    rows=$(($(wc -l < artifacts/demo-forecast.csv) - 1))
    green "  ✓ получено $rows почасовых значений → artifacts/demo-forecast.csv"

    printf '\n'
    bold "Прогноз мощности"
    show_forecast artifacts/demo-forecast.csv
    printf '\n'
    info "Полный прогноз февраля: artifacts/gfs-model/february_replay.csv"
    info "Метрики и ограничения:  artifacts/gfs-model/report.md"
}

# --- дашборд ----------------------------------------------------------------

WEB_PORT="${WEB_PORT:-3000}"

# Next.js хранит PID сервера в lock-файле. Проверяем команду и рабочую
# директорию процесса: останавливать чужой процесс по устаревшему PID нельзя.
web_pid() {
    command -v node >/dev/null 2>&1 || return 0
    node - "$PWD/apps/web" <<'NODE'
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');
const root = fs.realpathSync(process.argv[2]);
try {
    const { pid } = JSON.parse(fs.readFileSync(`${root}/.next/dev/lock`, 'utf8'));
    if (!Number.isInteger(pid) || pid <= 1) process.exit(0);
    process.kill(pid, 0);
    const command = execFileSync('ps', ['-p', String(pid), '-o', 'command='], { encoding: 'utf8' });
    if (!command.includes('next-server')) process.exit(0);
    let cwd;
    if (process.platform === 'linux') {
        cwd = fs.realpathSync(`/proc/${pid}/cwd`);
    } else {
        const output = execFileSync('lsof', ['-a', '-p', String(pid), '-d', 'cwd', '-Fn'], { encoding: 'utf8' });
        const line = output.split('\n').find((value) => value.startsWith('n'));
        if (line) cwd = fs.realpathSync(line.slice(1));
    }
    if (cwd === root) console.log(pid);
} catch { /* Нет запущенного сервера с подтверждённым владельцем. */ }
NODE
}

stop_web() {
    local pid
    pid=$(web_pid)
    if [ -n "$pid" ]; then
        info "останавливаю предыдущий дашборд этого проекта (PID $pid)…"
        kill "$pid" 2>/dev/null || true
        for _ in $(seq 1 20); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.25
        done
        if kill -0 "$pid" 2>/dev/null; then
            die "предыдущий дашборд ещё завершает работу" "Повторите запуск после его остановки."
        fi
    fi
    rm -f .run/web.pid
}

start_web() {
    command -v npm >/dev/null 2>&1 || die "нужны Node.js и npm" "Скачать: https://nodejs.org"
    stop_web
    mkdir -p .run

    # Наличие node_modules не означает, что зависимости нового коммита
    # установлены. Синхронизируем точные версии при изменении lock-файла.
    local dependencies saved=""
    dependencies=$(node -e '
        const fs = require("node:fs"), crypto = require("node:crypto");
        const hash = crypto.createHash("sha256");
        for (const file of ["package-lock.json", "package.json", "apps/web/package.json", "packages/ui/package.json"])
            hash.update(fs.readFileSync(file));
        console.log(hash.digest("hex"));')
    [ ! -f .run/web-dependencies.sha256 ] || saved=$(cat .run/web-dependencies.sha256)
    if [ "$saved" != "$dependencies" ] || ! node -e 'for (const name of ["next", "react", "three"]) require.resolve(name, { paths: ["./apps/web"] });' >/dev/null 2>&1; then
        bold "Синхронизирую зависимости дашборда по package-lock.json"
        npm ci --no-audit --no-fund || die "не удалось установить зависимости дашборда"
        printf '%s\n' "$dependencies" > .run/web-dependencies.sha256
    fi

    local first_port="$WEB_PORT"
    for _ in $(seq 1 10); do
        port_free "$WEB_PORT" && break
        WEB_PORT=$((WEB_PORT + 1))
    done
    port_free "$WEB_PORT" || die "нет свободного порта для дашборда" "Задайте WEB_PORT: WEB_PORT=3100 ./run.sh all"
    [ "$WEB_PORT" = "$first_port" ] || info "порт $first_port занят, использую $WEB_PORT"

    bold "Запуск дашборда (порт $WEB_PORT)"
    # Next.js проксирует /api на backend; браузер обращается к своему origin.
    local pid
    pid=$(node - "$PWD" "$WEB_PORT" "$PORT" <<'NODE'
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const [root, port, backendPort] = process.argv.slice(2);
const log = fs.openSync(`${root}/.run/web.log`, 'w');
const child = spawn(process.execPath, [
    `${root}/node_modules/next/dist/bin/next`, 'dev', '--hostname', '127.0.0.1', '--port', port,
], {
    cwd: `${root}/apps/web`, detached: true, stdio: ['ignore', log, log],
    env: { ...process.env, RENTBOX_API_URL: `http://127.0.0.1:${backendPort}/api` },
});
child.on('error', (error) => { console.error(error.message); process.exitCode = 1; });
child.unref();
fs.closeSync(log);
console.log(child.pid);
NODE
    )
    printf '%s\n' "$pid" > .run/web.pid

    printf '  ожидаю дашборд'
    for _ in $(seq 1 45); do
        if ! kill -0 "$pid" 2>/dev/null; then
            printf '\n'
            tail -40 .run/web.log
            die "процесс дашборда завершился" "Полный журнал: .run/web.log"
        fi
        local status
        status=$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$WEB_PORT" 2>/dev/null || true)
        if [ "$status" = "200" ] && curl -fsS --max-time 5 "http://127.0.0.1:$WEB_PORT/api/health" >/dev/null 2>&1; then
            printf '\n'
            green "  ✓ дашборд и подключение к API работают"
            return 0
        fi
        if [ "$status" = "500" ]; then
            printf '\n'
            tail -40 .run/web.log
            die "ошибка сборки страницы дашборда" "Полный журнал: .run/web.log"
        fi
        printf '.'
        sleep 2
    done
    printf '\n'
    tail -40 .run/web.log
    die "дашборд или его соединение с API не готовы" "Журнал: tail -50 .run/web.log"
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

# Человекочитаемый вид результата. Сам CSV остаётся машинным: технические имена
# колонок, время UTC и доли 0…1 — это контракт для проверяющих и скриптов.
show_forecast() {
    local file="$1"
    if ! command -v python3 >/dev/null 2>&1; then
        head -5 "$file" | sed 's/^/  /'
        return 0
    fi
    python3 - "$file" <<'RENDER' || head -5 "$file" | sed 's/^/  /'
import csv, datetime, sys

OFFSET = 5  # часовой пояс исходных измерений, см. RENTBOX_SOURCE_TIMEZONE

def local(value):
    moment = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment + datetime.timedelta(hours=OFFSET)

with open(sys.argv[1]) as handle:
    rows = list(csv.DictReader(handle))
if not rows:
    raise SystemExit("  файл пуст")

print(f"  {'Турбина':<9}{'Местное время (UTC+5)':<24}{'Через':<8}{'Мощность':>9}")
for row in rows[:5]:
    print(f"  {row['turbine_id']:<9}{local(row['valid_time']).strftime('%d.%m %H:%M'):<24}"
          f"{'+' + row['lead_hour'] + ' ч':<8}{float(row['predicted_power']) * 100:>8.1f}%")

power = [float(row["predicted_power"]) for row in rows]
turbines = sorted({row["turbine_id"] for row in rows})
hours = len({row["valid_time"] for row in rows})
start, end = local(rows[0]["valid_time"]), local(rows[-1]["valid_time"])
print(f"\n  {hours} часов × {len(turbines)} турбины = {len(rows)} значений")
print(f"  Период: {start:%d.%m %H:%M} — {end:%d.%m %H:%M} по местному времени")
print(f"  Мощность от {min(power) * 100:.1f}% до {max(power) * 100:.1f}% номинала, "
      f"в среднем {sum(power) / len(power) * 100:.1f}%")
RENDER
}

# --- остановка --------------------------------------------------------------

stop() {
    stop_web
    detect_compose
    if [ -n "$COMPOSE" ] && docker info >/dev/null 2>&1; then
        $COMPOSE down 2>/dev/null || true
    fi
    for name in backend; do
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

# --- меню ------------------------------------------------------------------

menu() {
    printf '\n'
    bold "RentBox — прогноз выработки ВЭС"
    printf '\n'
    printf '  \033[1m1\033[0m  Посчитать прогноз          на 48 часов вперёд для двух турбин\n'
    printf '  \033[1m2\033[0m  Сервис и дашборд           backend + интерфейс в браузере\n'
    printf '  \033[1m3\033[0m  Только сервис              backend и документация API\n'
    printf '  \033[1m4\033[0m  Проверить окружение        ничего не запускает\n'
    printf '  \033[1m5\033[0m  Журнал                     последние 50 строк\n'
    printf '  \033[1m6\033[0m  Остановить                 все запущенные сервисы\n'
    printf '  \033[1m0\033[0m  Выход\n'
    printf '\n'
    printf 'Выберите пункт [1]: '
    read -r answer
    printf '\n'

    case "${answer:-1}" in
        1) demo ;;
        2) all ;;
        3) start ;;
        4) check; green "Окружение готово, режим: $MODE" ;;
        5) logs ;;
        6) stop ;;
        0) exit 0 ;;
        *) red "Нет такого пункта: $answer"; exit 1 ;;
    esac
}

# Без аргументов в живом терминале показываем меню; в скриптах и CI —
# прежнее поведение, чтобы автоматизация не зависла на вводе.
if [ $# -eq 0 ]; then
    if [ -t 0 ] && [ -t 1 ]; then
        menu
        exit 0
    fi
    set -- start
fi

case "$1" in
    start) start ;;
    all)   all ;;
    demo)  demo ;;
    check) check; green "Окружение готово, режим: $MODE" ;;
    stop)  stop ;;
    logs)  logs ;;
    *)     die "неизвестная команда: $1" "Доступно: start, all, demo, check, stop, logs" ;;
esac
