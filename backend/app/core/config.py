from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RENTBOX_",
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "RentBox Energy API"
    turbines_file: Path = BACKEND_DIR / "config" / "turbines.json"
    audit_file: Path = PROJECT_DIR / "reports" / "data-audit.json"
    input_dir: Path = PROJECT_DIR / "data" / "incoming"
    database_path: Path = PROJECT_DIR / "data" / "forecasts.duckdb"
    agent_factory: str | None = "src.agent:create_agent"
    source_timezone: str | None = None
    timestamp_meaning: Literal["interval_start", "interval_end"] | None = None
    time_configuration_confirmed: bool = False
    allow_research_time_settings: bool = False
    max_pending_runs: int = Field(default=128, ge=1, le=1000)
    max_replay_runs: int = Field(default=62, ge=1, le=366)
    max_events_per_run: int = Field(default=500, ge=20, le=5000)
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )

    @field_validator("source_timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("source_timezone must be a valid IANA timezone") from exc
        return value

    @property
    def missing_time_settings(self) -> list[str]:
        names = ("source_timezone", "timestamp_meaning", "time_configuration_confirmed")
        return [name for name in names if not getattr(self, name)]

    @property
    def blocking_time_settings(self) -> list[str]:
        return [name for name in self.missing_time_settings
                if name != "time_configuration_confirmed" or not self.allow_research_time_settings]
