UV ?= $(if $(wildcard $(CURDIR)/.tools/bin/uv),$(CURDIR)/.tools/bin/uv,uv)
export UV_CACHE_DIR := $(CURDIR)/.tools/uv-cache
export UV_PYTHON_INSTALL_DIR := $(CURDIR)/.tools/python

.PHONY: setup dev run test lint format openapi

setup:
	"$(UV)" sync --project backend --frozen

dev: setup
	backend/.venv/bin/uvicorn src.api:app --reload --host 127.0.0.1 --port 8000

run: setup
	backend/.venv/bin/uvicorn src.api:app --host 127.0.0.1 --port 8000 --workers 1

test:
	cd backend && .venv/bin/pytest

lint:
	backend/.venv/bin/ruff check --config backend/pyproject.toml backend/app backend/tests backend/scripts src/api.py
	backend/.venv/bin/ruff format --config backend/pyproject.toml --check backend/app backend/tests backend/scripts src/api.py

format:
	backend/.venv/bin/ruff check --config backend/pyproject.toml --fix backend/app backend/tests backend/scripts src/api.py
	backend/.venv/bin/ruff format --config backend/pyproject.toml backend/app backend/tests backend/scripts src/api.py

openapi:
	backend/.venv/bin/python backend/scripts/export_openapi.py
