#!/usr/bin/env bash
# Запуск Windcast одной командой.
#
#   ./run.sh          меню выбора (или сразу запуск, если терминал неинтерактивный)
#   ./run.sh all      поднять backend и дашборд вместе
#   ./run.sh web      подключить дашборд к уже запущенному backend
#   ./run.sh demo     поднять и сразу посчитать прогноз на 48 часов
#   ./run.sh check    только проверить окружение, ничего не запускать
#   ./run.sh stop     остановить
#   ./run.sh logs     показать журнал сервиса
#   ./run.sh settings  OpenAI: ChatGPT / API key / отключить
#
# Ключи и внешние учётные записи не нужны: прогнозы погоды лежат в репозитории
# (data/gfs-runs), модель — в artifacts. Достаточно Docker; если его нет,
# скрипт поднимет сервис локально через uv.

set -euo pipefail

cd "$(dirname "$0")"

PORT="${BACKEND_PORT:-8000}"
COMPOSE=""
MODE=""
OPENAI_MODE="api_key"

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

# Read only two non-secret flags. Never source dotenv as executable shell code.
helper_setting() {
    local key="$1" fallback="$2"
    if [ -n "${!key+x}" ]; then
        printf '%s\n' "${!key}"
        return
    fi
    local files=(/dev/null)
    [ ! -f .env ] || files+=(.env)
    [ ! -f backend/.env ] || files+=(backend/.env)
    awk -v key="$key" -v fallback="$fallback" '
        BEGIN { value=fallback; quote=sprintf("%c",39) }
        {
            line=$0
            sub(/^[ \t]*export[ \t]+/, "", line)
            if (line ~ "^[ \\t]*" key "[ \\t]*=") {
                sub("^[ \\t]*" key "[ \\t]*=[ \\t]*", "", line)
                sub(/[ \t]+#.*/, "", line)
                sub(/[ \t\r]+$/, "", line)
                first=substr(line,1,1)
                if ((first == "\"" || first == quote) && substr(line,length(line),1) == first)
                    line=substr(line,2,length(line)-2)
                value=line
            }
        }
        END { print value }
    ' "${files[@]}"
}

helper_mode() {
    local enabled
    enabled=$(helper_setting OPENAI_HELPER_ENABLED true | tr '[:upper:]' '[:lower:]')
    case "$enabled" in
        false|0|off|no) OPENAI_MODE="off"; return ;;
        true|1|on|yes) ;;
        *) die "неверное OPENAI_HELPER_ENABLED" "Исправить: ./run.sh settings" ;;
    esac
    OPENAI_MODE=$(helper_setting OPENAI_HELPER_AUTH_MODE api_key)
    case "$OPENAI_MODE" in
        api_key|chatgpt) ;;
        *) die "неверное OPENAI_HELPER_AUTH_MODE" "Исправить: ./run.sh settings" ;;
    esac
}

settings_python() {
    local candidate
    for candidate in backend/.venv/bin/python ../.venv/bin/python .venv/bin/python; do
        if [ -x "$candidate" ]; then printf '%s\n' "$candidate"; return; fi
    done
    command -v python3 || return 1
}

openai_settings() {
    local python
    python=$(settings_python) || die "для мастера OpenAI нужен Python 3"
    ensure_env
    "$python" scripts/configure_openai.py "$@"
}

check() {
    bold "Проверка окружения"
    local ready=1

    MODE=""
    helper_mode
    detect_compose
    if [ "$OPENAI_MODE" = "chatgpt" ]; then
        info "ChatGPT: локальный backend, Codex использует текущий вход пользователя."
        if ! command -v codex >/dev/null 2>&1; then
            red "  ✗ Codex CLI не найден"
            ready=0
        elif ! codex login status 2>&1 | grep -qi 'logged in using chatgpt'; then
            red "  ✗ нет подтверждённого входа Codex через ChatGPT: ./run.sh settings"
            ready=0
        fi
    elif [ -n "$COMPOSE" ] && docker info >/dev/null 2>&1; then
        green "  ✓ Docker готов — запуск в контейнере"
        MODE="docker"
    elif [ -n "$COMPOSE" ]; then
        info "  ⚠ Docker установлен, но демон не отвечает. Запустите Docker Desktop."
    else
        info "  · Docker не найден"
    fi

    if [ -z "$MODE" ]; then
        if [ -x backend/.venv/bin/python ] && [ -x backend/.venv/bin/uvicorn ]; then
            green "  ✓ готовое окружение backend/.venv — локальный запуск"
            MODE="local"
        elif command -v uv >/dev/null 2>&1 || [ -x .tools/bin/uv ]; then
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
    chmod 600 .env
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

# --- мастер первоначальной настройки ----------------------------------------

# Записывает .env по шагам. На каждом шаге Enter принимает значение
# по умолчанию, "s" пропускает остаток мастера и берёт дефолты для всего.
SETUP_TZ="Etc/GMT-5"
SETUP_MEANING="interval_start"
SETUP_RESEARCH="true"
SETUP_BACKEND_PORT="8000"
SETUP_WEB_PORT="3000"
SETUP_SKIPPED=0

ask() {
    # ask <подсказка> <значение по умолчанию> -> ответ в REPLY_VALUE
    local prompt="$1" fallback="$2" answer
    printf '  %s [%s]: ' "$prompt" "$fallback"
    read -r answer
    case "$answer" in
        s|S|п|П) SETUP_SKIPPED=1; REPLY_VALUE="$fallback" ;;
        "")      REPLY_VALUE="$fallback" ;;
        *)       REPLY_VALUE="$answer" ;;
    esac
}

step_time() {
    [ "$SETUP_SKIPPED" -eq 1 ] && return 0
    printf '\n'
    bold "Шаг 1 из 3. Время в исходных данных"
    info "Организаторы не сообщили, в каком поясе записаны CSV и что означает"
    info "метка десятиминутного интервала. От этого зависит сопоставление с погодой."
    printf '\n'
    printf '    1  Исследовательские настройки: UTC+5, метка = начало интервала\n'
    printf '       Так обучена текущая модель. Результаты помечаются как research.\n'
    printf '    2  Подтверждённые организаторами — ввести свои значения\n'
    printf '\n'
    ask "Вариант" "1"
    [ "$SETUP_SKIPPED" -eq 1 ] && return 0

    if [ "$REPLY_VALUE" = "2" ]; then
        ask "Часовой пояс IANA" "Etc/GMT-5";      SETUP_TZ="$REPLY_VALUE"
        ask "Метка интервала (interval_start / interval_end)" "interval_start"
        SETUP_MEANING="$REPLY_VALUE"
        SETUP_RESEARCH="false"
        info "Настройки помечены как подтверждённые."
    else
        info "Оставлены исследовательские значения."
    fi
}

step_ports() {
    [ "$SETUP_SKIPPED" -eq 1 ] && return 0
    printf '\n'
    bold "Шаг 2 из 3. Порты"
    info "Занятый порт скрипт обойдёт сам, выбрав следующий свободный."
    printf '\n'
    ask "Порт API" "8000";      SETUP_BACKEND_PORT="$REPLY_VALUE"
    [ "$SETUP_SKIPPED" -eq 1 ] && return 0
    ask "Порт дашборда" "3000"; SETUP_WEB_PORT="$REPLY_VALUE"
}

step_training() {
    [ "$SETUP_SKIPPED" -eq 1 ] && return 0
    printf '\n'
    bold "Шаг 3 из 3. Обучение (необязательно)"
    info "Готовая модель уже в репозитории и считается на CPU."
    info "Переобучение нужно, только если хотите повторить эксперимент."
    printf '\n'
    if [ -x scripts/train.sh ]; then
        ./scripts/train.sh --check 2>/dev/null | sed 's/^/  /' || true
    fi
    printf '\n'
    info "Запустить позже: ./scripts/train.sh либо пункт 7 в меню."
    info "Облачная NVIDIA Brev: ./scripts/train.sh --cloud"
}

write_env() {
    cp .env.example .env
    chmod 600 .env
    cat >> .env <<SETTINGS

# Записано мастером ./run.sh setup
RENTBOX_SOURCE_TIMEZONE=$SETUP_TZ
RENTBOX_TIMESTAMP_MEANING=$SETUP_MEANING
RENTBOX_ALLOW_RESEARCH_TIME_SETTINGS=$SETUP_RESEARCH
BACKEND_PORT=$SETUP_BACKEND_PORT
WEB_PORT=$SETUP_WEB_PORT
SETTINGS
}

setup() {
    bold "Первоначальная настройка Windcast"
    info "Enter — принять значение в скобках, s — пропустить и взять всё по умолчанию."
    if [ -f .env ]; then
        printf '\n'
        info "Файл .env уже существует."
        ask "Перезаписать? (y/n)" "n"
        case "$REPLY_VALUE" in y|Y|д|Д) ;; *) info "Оставлен прежний .env."; return 0 ;; esac
    fi

    step_time
    step_ports
    step_training
    write_env

    printf '\n'
    bold "Настройки сохранены в .env"
    # printf выравнивает по байтам, а кириллица занимает по два — поэтому
    # без табличной ширины, просто «ключ: значение».
    info "Часовой пояс исходных данных: $SETUP_TZ"
    info "Метка интервала: $SETUP_MEANING"
    info "Режим research: $SETUP_RESEARCH"
    info "Порт API: $SETUP_BACKEND_PORT"
    info "Порт дашборда: $SETUP_WEB_PORT"
    [ "$SETUP_SKIPPED" -eq 1 ] && info "" && info "Мастер пропущен, применены значения по умолчанию."
    printf '\n'
    info "Дальше: ./run.sh demo — посчитать прогноз"
}

# --- запуск -----------------------------------------------------------------

wait_healthy() {
    local url="http://127.0.0.1:$PORT/api/health"
    local tracked_pid="${1:-}"
    printf '  ожидаю готовности'
    for _ in $(seq 1 60); do
        if [ -n "$tracked_pid" ] && ! kill -0 "$tracked_pid" 2>/dev/null; then
            printf '\n'
            tail -40 .run/backend.log
            die "локальный backend завершился" "Журнал: .run/backend.log"
        fi
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
    output=$(BACKEND_PORT="$PORT" $COMPOSE up -d --build --wait backend 2>&1) || result=$?
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
    if [ ! -x backend/.venv/bin/uvicorn ]; then
        local uv_bin="uv"
        [ -x .tools/bin/uv ] && uv_bin=".tools/bin/uv"
        info "устанавливаю зависимости…"
        UV_CACHE_DIR="$PWD/.tools/uv-cache" UV_PYTHON_INSTALL_DIR="$PWD/.tools/python" \
            "$uv_bin" sync --project backend --frozen >/dev/null
    fi
    # Settings reads .env as dotenv; sourcing it as shell would corrupt JSON values.
    mkdir -p .run
    if [ "$OPENAI_MODE" = "chatgpt" ]; then
        info "История локальной проверки: .run/chatgpt/forecasts.duckdb (отдельно от Docker)."
        info "Backend и сайт доступны только через 127.0.0.1."
    fi
    backend/.venv/bin/python - "$PORT" "$OPENAI_MODE" <<'PYTHON'
import os
import subprocess
import sys
from pathlib import Path

root = Path.cwd()
port, auth_mode = sys.argv[1:]
environment = os.environ.copy()
if auth_mode == "chatgpt":
    state = root / ".run/chatgpt"
    state.mkdir(parents=True, exist_ok=True)
    environment["RENTBOX_DATABASE_PATH"] = str(state / "forecasts.duckdb")
with (root / ".run/backend.log").open("w") as log:
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.api:app", "--host", "127.0.0.1", "--port", port],
        cwd=root, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        start_new_session=True,
    )
(root / ".run/backend.pid").write_text(str(process.pid) + "\n")
(root / ".run/backend.port").write_text(port + "\n")
PYTHON
    wait_healthy "$(cat .run/backend.pid)"
}

local_pid() {
    [ -f .run/backend.pid ] || return 0
    local python
    python=$(settings_python) || return 0
    "$python" - "$PWD" <<'PYTHON'
import os
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
try:
    pid = int((root / ".run/backend.pid").read_text().strip())
    if pid <= 1:
        raise ValueError("Invalid PID")
    os.kill(pid, 0)
    if sys.platform == "linux":
        process = Path(f"/proc/{pid}")
        args = (process / "cmdline").read_bytes().split(b"\0")
        valid = b"src.api:app" in args and any(b"uvicorn" == arg or arg.endswith(b"/uvicorn") for arg in args)
        cwd = (process / "cwd").resolve()
    else:
        args = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
        valid = "uvicorn" in args and "src.api:app" in args
        fields = subprocess.check_output(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], text=True)
        cwd = next(Path(line[1:]).resolve() for line in fields.splitlines() if line.startswith("n"))
    if valid and cwd == root:
        print(pid)
except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
    pass
PYTHON
}

stop_local() {
    local pid stored=""
    pid=$(local_pid)
    if [ -z "$pid" ] && [ -f .run/backend.pid ]; then
        stored=$(cat .run/backend.pid)
        if [[ "$stored" =~ ^[1-9][0-9]*$ ]] && [ "$stored" -gt 1 ] && kill -0 "$stored" 2>/dev/null; then
            die "не удалось подтвердить владельца PID $stored из .run/backend.pid" \
                "Процесс не остановлен. Проверьте этот PID перед повторным запуском."
        fi
    fi
    if [ -n "$pid" ]; then
        info "останавливаю предыдущий локальный backend этого проекта (PID $pid)…"
        kill "$pid" 2>/dev/null || true
        for _ in $(seq 1 40); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.25
        done
        if kill -0 "$pid" 2>/dev/null; then
            die "локальный backend ещё завершает работу" "Повторите запуск после его остановки."
        fi
    fi
    rm -f .run/backend.pid .run/backend.port
}

start() {
    ensure_env
    check
    # Повторный запуск использует порт контейнера этого Compose-проекта.
    # Иначе каждый ./run.sh all пересоздавал его на следующем порту.
    local published=""
    if [ "$MODE" = "docker" ]; then
        published=$($COMPOSE port backend 8000 2>/dev/null || true)
        published="${published##*:}"
    else
        stop_local
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

# Reconnect the dashboard after another launcher changed the backend port.
# This command never starts, stops or recreates the backend.
web() {
    helper_mode
    detect_compose
    local published="" pid=""
    if [ "$OPENAI_MODE" != "chatgpt" ] && [ -n "$COMPOSE" ]; then
        published=$($COMPOSE port backend 8000 2>/dev/null || true)
        published="${published##*:}"
    fi
    if [[ "$published" =~ ^[0-9]+$ ]] && curl -fsS --max-time 5 "http://127.0.0.1:$published/api/health" >/dev/null 2>&1; then
        PORT="$published"
    else
        pid=$(local_pid)
        if [ -z "$pid" ] || [ ! -f .run/backend.port ]; then
            die "не найден готовый backend выбранного режима" "Поднять сервисы: ./run.sh all"
        fi
        PORT=$(cat .run/backend.port)
        [[ "$PORT" =~ ^[0-9]+$ ]] || die "некорректный порт в .run/backend.port"
        curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 \
            || die "локальный backend на порту $PORT не отвечает" "Журнал: ./run.sh logs"
    fi
    info "Переподключаю дашборд к API на порту $PORT."
    start_web
    green "Дашборд: http://127.0.0.1:$WEB_PORT"
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
print(f"  Мощность от {min(power) * 100:.1f}% до {max(power) * 100:.1f}% нормализованной шкалы, "
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
    stop_local
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
    bold "Windcast — прогноз выработки ВЭС"
    printf '\n'
    printf '  \033[1m1\033[0m  Посчитать прогноз          на 48 часов вперёд для двух турбин\n'
    printf '  \033[1m2\033[0m  Сервис и дашборд           backend + интерфейс в браузере\n'
    printf '  \033[1m3\033[0m  Только сервис              backend и документация API\n'
    printf '  \033[1m4\033[0m  Проверить окружение        ничего не запускает\n'
    printf '  \033[1m5\033[0m  Журнал                     последние 50 строк\n'
    printf '  \033[1m6\033[0m  Остановить                 все запущенные сервисы\n'
    printf '  \033[1m7\033[0m  Переобучить модель         найдёт NVIDIA, иначе CPU\n'
    printf '  \033[1m8\033[0m  Настроить                  пояс, порты, обучение\n'
    printf '  \033[1m9\033[0m  Настройки OpenAI          аккаунт ChatGPT / API key / отключить\n'
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
        7) ./scripts/train.sh ;;
        8) setup ;;
        9) openai_settings ;;
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
    setup) setup ;;
    settings|openai) shift; openai_settings "$@" ;;
    start) start ;;
    all)   all ;;
    web)   web ;;
    demo)  demo ;;
    check) check; green "Окружение готово, режим: $MODE" ;;
    stop)  stop ;;
    logs)  logs ;;
    *)     die "неизвестная команда: $1" "Доступно: setup, settings, openai, start, all, web, demo, check, stop, logs" ;;
esac
