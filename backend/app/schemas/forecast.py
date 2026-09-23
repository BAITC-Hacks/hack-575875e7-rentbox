from datetime import timedelta
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BeforeValidator, Field, model_validator

from backend.app.schemas.common import SHA256, ErrorDetail, Schema, UTCDateTime
from backend.app.schemas.turbine import TurbineId

RunStatus = Literal["queued", "running", "completed", "failed"]
Stage = Literal["validate", "weather", "prepare", "model", "predict", "review", "save"]
AgentMode = Literal["llm", "policy"]


def require_integer(value: int) -> int:
    if type(value) is not int:
        raise ValueError("Use an integer number of hours")
    return value


def unique_turbines(values: list[int]) -> list[int]:
    if len(set(values)) != len(values):
        raise ValueError("turbine_ids must not contain duplicates")
    return sorted(values)


TurbineIds = Annotated[
    list[TurbineId], Field(min_length=1, max_length=2), AfterValidator(unique_turbines)
]
ForecastHorizon = Annotated[Literal[24, 48], BeforeValidator(require_integer)]


class ForecastRunCreate(Schema):
    as_of: UTCDateTime
    horizon_hours: ForecastHorizon = 48
    turbine_ids: TurbineIds = Field(default_factory=lambda: [1, 2])
    refresh_weather: bool = Field(default=False, strict=True)


class RunAccepted(Schema):
    run_id: str
    status: Literal["queued"] = "queued"


class AgentUpdate(Schema):
    stage: Stage
    progress: float = Field(ge=0, le=1)
    level: Literal["info", "warning", "error"] = "info"
    message: str = Field(min_length=1, max_length=2000)
    tool: str | None = None
    attempt: int = Field(default=1, ge=1)
    agent_mode: AgentMode | None = None


class AgentEvent(Schema):
    id: str
    timestamp: UTCDateTime
    stage: Stage
    level: Literal["info", "warning", "error"]
    message: str
    tool: str | None = None
    attempt: int = Field(default=1, ge=1)


class ForecastRunRead(Schema):
    run_id: str
    status: RunStatus = "queued"
    stage: Stage = "validate"
    progress: float = Field(default=0, ge=0, le=1)
    agent_mode: AgentMode
    as_of: UTCDateTime
    horizon_hours: ForecastHorizon
    turbine_ids: TurbineIds
    revision: int = Field(default=1, ge=1)
    supersedes_run_id: str | None = None
    reused_run_id: str | None = None
    events: list[AgentEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: ErrorDetail | None = None


class ForecastPoint(Schema):
    valid_time: UTCDateTime
    lead_hour: int = Field(strict=True, ge=1, le=48)
    predicted_power: float = Field(strict=True, ge=0, le=1)


class WeatherProvenance(Schema):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    initialization_time: UTCDateTime
    available_at: UTCDateTime
    availability_basis: str = Field(min_length=1)
    retrieved_at: UTCDateTime
    sha256: SHA256

    @model_validator(mode="after")
    def time_order(self) -> Self:
        if self.initialization_time > self.available_at:
            raise ValueError("Weather cannot be available before initialization")
        if self.available_at > self.retrieved_at:
            raise ValueError("Weather cannot be retrieved before availability")
        return self


class ComputedSeries(Schema):
    turbine_id: TurbineId
    points: list[ForecastPoint] = Field(min_length=24, max_length=48)
    weather: WeatherProvenance


class ForecastSeries(ComputedSeries):
    storage_run_id: int = Field(gt=0)


class ForecastAnalysis(Schema):
    summary: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class AgentResult(Schema):
    """Computed output before the backend writes any forecast rows."""

    input_sha256: SHA256
    agent_mode: AgentMode
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    training_data_available_until: UTCDateTime
    series: list[ComputedSeries] = Field(min_length=1, max_length=2)
    analysis: ForecastAnalysis

    def validate_for(self, request: ForecastRunCreate) -> None:
        if self.training_data_available_until > request.as_of:
            raise ValueError("Training targets were not yet available at as_of")
        if sorted(series.turbine_id for series in self.series) != request.turbine_ids:
            raise ValueError("Agent must return exactly the requested turbines")
        for series in self.series:
            if series.weather.available_at > request.as_of:
                raise ValueError("Weather was not yet available at as_of")
            if len(series.points) != request.horizon_hours:
                raise ValueError("Each turbine must contain the complete forecast horizon")
            for lead, point in enumerate(series.points, start=1):
                if point.lead_hour != lead:
                    raise ValueError("Forecast hours must be unique and ordered from 1")
                if point.valid_time != request.as_of + timedelta(hours=lead):
                    raise ValueError("valid_time must equal as_of + lead_hour")


class ForecastRead(Schema):
    run_id: str
    as_of: UTCDateTime
    horizon_hours: ForecastHorizon
    unit: Literal["normalized_power"] = "normalized_power"
    model_version: str
    training_data_available_until: UTCDateTime
    series: list[ForecastSeries]
    analysis: ForecastAnalysis


class ReplayCreate(Schema):
    first_as_of: UTCDateTime
    last_as_of: UTCDateTime
    step_hours: Annotated[Literal[24], BeforeValidator(require_integer)] = 24
    horizon_hours: ForecastHorizon = 48
    turbine_ids: TurbineIds = Field(default_factory=lambda: [1, 2])

    @model_validator(mode="after")
    def ordered_dates(self) -> Self:
        seconds = (self.last_as_of - self.first_as_of).total_seconds()
        if seconds < 0 or seconds % (self.step_hours * 3600):
            raise ValueError("Replay bounds must be ordered and separated by whole daily steps")
        return self

    @property
    def total_runs(self) -> int:
        return int((self.last_as_of - self.first_as_of).total_seconds() // 86400) + 1


class ReplayAccepted(Schema):
    replay_id: str
    status: Literal["queued"] = "queued"


class ReplayRead(Schema):
    replay_id: str
    status: RunStatus = "queued"
    total_runs: int
    completed_runs: int = 0
    failed_runs: int = 0
    run_ids: list[str]
    error: ErrorDetail | None = None
