#!/usr/bin/env bash
set -euo pipefail
mkdir -p artifacts/gfs-download
python_bin="${PYTHON_BIN:-.venv/bin/python}"
starts=(2024-03-01 2024-09-01 2025-03-01 2025-09-01)
ends=(2024-08-31 2025-02-28 2025-08-31 2026-01-30)
jobs=()
for i in 0 1 2 3; do
  OPENBLAS_NUM_THREADS=1 "$python_bin" -u -m scripts.fetch_gfs_runs \
    --start "${starts[$i]}" --end "${ends[$i]}" --workers 6 \
    > "artifacts/gfs-download/part-$i.log" 2>&1 &
  jobs+=("$!")
done
status=0
for pid in "${jobs[@]}"; do
  wait "$pid" || status=1
done
exit "$status"
