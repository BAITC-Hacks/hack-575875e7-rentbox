from typing import Literal

from backend.app.schemas.common import SHA256, Schema
from backend.app.schemas.turbine import TurbineId


class TimeConfiguration(Schema):
    source_timezone: str | None
    timestamp_meaning: Literal["interval_start", "interval_end"] | None
    confirmed: bool
    missing_fields: list[str]


class TurbineDataSummary(Schema):
    turbine_id: TurbineId
    file: str
    sha256: SHA256
    rows: int
    start_local: str
    end_local: str
    source_matches_audit: bool
    missing_percent: float
    missing_10min_records: int
    full_hours: int
    partial_hours: int
    empty_hours: int
    january_2026_complete: bool
    records_from_february_2026: int


class DataSummary(Schema):
    unit: Literal["normalized_power"] = "normalized_power"
    time_configuration: TimeConfiguration
    turbines: list[TurbineDataSummary]
    february_actuals_available: bool
    february_metrics: None = None
    warnings: list[str]
