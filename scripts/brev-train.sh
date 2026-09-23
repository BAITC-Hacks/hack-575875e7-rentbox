#!/usr/bin/env bash
# Execute only after approval to install the isolated cloud training environment.
set -euo pipefail

training_root=/tmp/wind-training
mkdir -p "$training_root"
tar -xzf /tmp/brev-training.tar.gz -C "$training_root"
cd "$training_root"

# uv is copied from our existing installation; no third-party shell installer.
chmod +x /tmp/wind-uv
if [ ! -x .venv/bin/python ]; then
    /tmp/wind-uv venv --python 3.12 .venv
fi
/tmp/wind-uv pip install --python .venv/bin/python -r requirements.txt
/tmp/wind-uv pip install --python .venv/bin/python 'torch==2.11.0' --index-url https://download.pytorch.org/whl/cu128

.venv/bin/python - <<'PY'
import json, platform, torch
from importlib.metadata import version
from pathlib import Path
if not torch.cuda.is_available():
    raise SystemExit('CUDA unavailable; refusing silent CPU fallback')
evidence = {'hostname': platform.node(), 'python': platform.python_version(),
            'gpu': torch.cuda.get_device_name(0), 'cuda': torch.version.cuda,
            'versions': {p: version(p) for p in ['torch', 'numpy', 'pandas', 'scikit-learn', 'pyarrow']}}
Path('artifacts/search/cloud-environment.json').write_text(json.dumps(evidence, indent=2)+'\n')
print(json.dumps(evidence), flush=True)
PY

.venv/bin/python -m scripts.search_models train --worker cloud-gpu --device cuda
tar -czf /tmp/wind-results.tar.gz artifacts/search/cloud-gpu artifacts/search/cloud-environment.json
