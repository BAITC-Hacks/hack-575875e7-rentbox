"""ASGI entrypoint shared with the agent team: uvicorn src.api:app."""

from backend.app.main import app, create_app

__all__ = ["app", "create_app"]
