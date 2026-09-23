#!/usr/bin/env bash
# Проверка NVIDIA NIM. .env читается как dotenv, без выполнения shell-команд.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -n "${PYTHON:-}" ]; then
    exec "$PYTHON" -m scripts.nvidia_api check "$@"
fi
for candidate in backend/.venv/bin/python .venv/bin/python ../.venv/bin/python python3; do
    if "$candidate" -c 'import httpx, pydantic_settings' >/dev/null 2>&1; then
        exec "$candidate" -m scripts.nvidia_api check "$@"
    fi
done
printf '%s\n' 'Нужен Python с зависимостями backend. Выполните make setup или задайте PYTHON.' >&2
exit 1
