FROM ghcr.io/astral-sh/uv:0.12.18 AS uv
FROM python:3.12.14-slim

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/backend/.venv/bin:$PATH"

COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN uv sync --project backend --frozen --no-dev --no-cache
COPY backend/__init__.py ./backend/__init__.py
COPY backend/app ./backend/app
COPY backend/config ./backend/config
COPY src ./src
COPY reports ./reports
COPY data/incoming ./data/incoming
RUN useradd --uid 10001 --create-home appuser && \
    mkdir -p /app/state && chown appuser:appuser /app/state
USER appuser
ENV RENTBOX_DATABASE_PATH=/app/state/forecasts.duckdb
EXPOSE 8000
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
