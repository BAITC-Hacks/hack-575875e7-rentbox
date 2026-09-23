#!/usr/bin/env bash
# Почасовой коммит — требование п. 5.4.8 Положения (ред. 23.09.2026): за каждый отчётный
# час нужен подтверждённый промежуточный результат, иначе дисквалификация (п. 5.9.2).
# Соревновательная часть: 23.09, 13:00-18:00 (п. 3.5, 5.3.1).
#
#   ./scripts/hourly-commit.sh "что сделали за этот час"
#   ./scripts/hourly-commit.sh --watch     # напоминать каждые 50 минут
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || { echo "не git-репозиторий" >&2; exit 1; })"

if [[ "${1:-}" == "--watch" ]]; then
  echo "Напоминания каждые 50 минут. Ctrl+C — выход."
  while true; do
    sleep 3000
    last=$(git log -1 --format=%cr 2>/dev/null || echo "коммитов нет")
    printf '\n\a=== НАПОМИНАНИЕ: последний коммит %s. Нужен коммит за этот час (п. 5.4.8) ===\n\n' "$last"
  done
fi

msg="${1:-}"
if [[ -z "$msg" ]]; then
  echo "Опиши прогресс: ./scripts/hourly-commit.sh \"добавлен парсер CSV и график\"" >&2
  exit 1
fi

git add -A
if git diff --cached --quiet; then
  echo "Изменений нет. Если за час ничего не поменялось — это риск дисквалификации (п. 5.4.8, 5.9.2)." >&2
  exit 1
fi

git commit -m "$msg"
git push 2>/dev/null || echo "ВНИМАНИЕ: push не прошёл. Итоговая версия — то, что в репозитории на 18:00 (п. 5.4.13)!" >&2
git log --oneline -1
