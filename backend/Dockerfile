FROM ghcr.io/astral-sh/uv:0.12.18 AS uv
FROM python:3.12.14-slim

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/backend/.venv/bin:$PATH"

# Нативная библиотека ecCodes нужна для разбора GRIB при обновлении архива
# погоды (refresh_weather=true). Python-обёртка gribapi без неё не работает.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libeccodes0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN uv sync --project backend --frozen --no-dev --no-cache
COPY backend/__init__.py ./backend/__init__.py
COPY backend/app ./backend/app
COPY backend/config ./backend/config
COPY src ./src
COPY scripts/fetch_gfs_runs.py ./scripts/
COPY reports ./reports
COPY data/incoming ./data/incoming
COPY data/weather ./data/weather
COPY data/gfs-runs ./data/gfs-runs
COPY artifacts/ensemble ./artifacts/ensemble
COPY artifacts/gfs-model ./artifacts/gfs-model
RUN useradd --uid 10001 --create-home appuser && \
    mkdir -p /app/state && chown appuser:appuser /app/state
USER appuser
ENV RENTBOX_DATABASE_PATH=/app/state/forecasts.duckdb \
    RENTBOX_WEATHER_CACHE=/app/state/weather \
    RENTBOX_GFS_CACHE=/app/state/gfs
EXPOSE 8000
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
