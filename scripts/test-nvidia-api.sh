#!/usr/bin/env bash
# Проверка доступа к NVIDIA API (build.nvidia.com) и списка доступных моделей.
#   ./scripts/test-nvidia-api.sh
set -euo pipefail

[[ -f .env ]] && set -a && source .env && set +a
KEY="${NVIDIA_API_KEY:-}"
BASE="${NVIDIA_BASE_URL:-https://integrate.api.nvidia.com/v1}"
MODEL="${NVIDIA_MODEL:-nvidia/llama-3.3-nemotron-super-49b-v1.5}"

if [[ -z "$KEY" ]]; then
  echo "NVIDIA_API_KEY не задан."
  echo "Ключ: https://build.nvidia.com/ → Get API Key (начинается с nvapi-)."
  echo "Затем: echo 'NVIDIA_API_KEY=nvapi-...' >> .env"
  exit 1
fi

echo "=== Доступные модели (первые 15) ==="
curl -s "$BASE/models" -H "Authorization: Bearer $KEY" | jq -r '.data[].id' 2>/dev/null | head -15 || echo "(не удалось получить список)"

echo
echo "=== Пробный запрос к $MODEL ==="
curl -s "$BASE/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Ответь одним словом: работает?\"}],\"max_tokens\":20}" \
  | jq -r '.choices[0].message.content // .' 2>/dev/null || echo "(ошибка запроса)"
