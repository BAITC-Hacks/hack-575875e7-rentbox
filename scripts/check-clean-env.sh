#!/usr/bin/env bash
# Проверка «как у технического эксперта»: клонируем репозиторий в чистую папку и поднимаем через Docker.
# П. 5.4.16 / 5.6.5 Положения (ред. 23.09.2026): если итоговую версию не удаётся запустить по
# инструкциям из репозитория, команда НЕ допускается к отбору — пояснения не принимаются.
# Запуск идёт на .env из .env.example, то есть заодно проверяет п. 5.6.6: ключевая
# функциональность должна работать без личных аккаунтов и подписок участников.
#
#   ./scripts/check-clean-env.sh [url-или-путь-репозитория]
set -euo pipefail

REPO="${1:-$(git rev-parse --show-toplevel)}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "=== 1. Клонирую в чистую папку: $TMP"
git clone --quiet "$REPO" "$TMP/proj"
cd "$TMP/proj"

echo "=== 2. Обязательные файлы"
fail=0
for f in README.md; do
  [[ -f "$f" ]] && echo "  ✓ $f" || { echo "  ✗ НЕТ $f — README обязателен (п. 5.4.15, 5.6.4)"; fail=1; }
done
if [[ -f .env.example ]]; then echo "  ✓ .env.example"; else echo "  ⚠ нет .env.example — эксперт не узнает про параметры окружения (п. 5.4.15)"; fi
if [[ -f docker-compose.yml || -f compose.yml || -f Makefile || -f run.sh ]]; then
  echo "  ✓ способ запуска одной командой"
else
  echo "  ✗ нет docker-compose.yml / Makefile / run.sh — запуск в чистом окружении под вопросом"; fail=1
fi
if [[ -f .env ]]; then echo "  ✗ .env ПОПАЛ В РЕПОЗИТОРИЙ — уберите секреты!"; fail=1; fi

echo "=== 3. Пробую поднять через Docker"
if [[ -f docker-compose.yml || -f compose.yml ]]; then
  cp -n .env.example .env 2>/dev/null || true
  if docker compose up --build -d --wait --wait-timeout 180; then
    echo "  ✓ сервисы поднялись"
    docker compose ps
    docker compose down -v >/dev/null 2>&1
  else
    echo "  ✗ docker compose up НЕ отработал — эксперт увидит то же самое, это снятие с отбора (п. 5.4.16)"
    docker compose logs --tail 30 || true
    docker compose down -v >/dev/null 2>&1
    fail=1
  fi
else
  echo "  — compose-файла нет, пропускаю"
fi

echo
[[ $fail -eq 0 ]] && echo "ИТОГ: проект запускается в чистом окружении на дефолтном .env ✓ (п. 5.4.16, 5.6.6)" || { echo "ИТОГ: есть проблемы — см. ✗ выше"; exit 1; }
