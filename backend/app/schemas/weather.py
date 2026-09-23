from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.app.schemas.common import SHA256, Schema, UTCDateTime

SourceId = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[a-zA-Z0-9_.:-]+$")]
PREVIOUS_RUNS_POLICY = "previous_runs_offset_plus_12h_v1"
PUBLICATION_MARGIN_HOURS = 12
ESTIMATED_AVAILABILITY_WARNING = (
    "Доступность погоды оценена по политике previous_runs_offset_plus_12h_v1 "
    "с запасом 12 часов. Точное историческое время публикации не подтверждено."
)


def previous_runs_availability(valid_time: datetime, forecast_offset_days: int) -> datetime:
    """Project policy estimate, not an observed publication timestamp."""
    return (
        valid_time
        - timedelta(days=forecast_offset_days)
        + timedelta(hours=PUBLICATION_MARGIN_HOURS)
    )


class WeatherSource(Schema):
    source_id: SourceId
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    retrieved_at: UTCDateTime
    sha256: SHA256


class SingleRunWeatherSource(WeatherSource):
    product: Literal["single_run"] = "single_run"
    initialization_time: UTCDateTime
    available_at: UTCDateTime
    availability_basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def time_order(self) -> Self:
        if self.initialization_time > self.available_at:
            raise ValueError("Weather cannot be available before initialization")
        if self.available_at > self.retrieved_at:
            raise ValueError("Weather cannot be retrieved before availability")
        return self


class PreviousRunsWeatherSource(WeatherSource):
    product: Literal["previous_runs"] = "previous_runs"
    initialization_time: None = None
    available_at: None = None
    availability_basis: Literal["previous_runs_offset_plus_12h_v1"] = PREVIOUS_RUNS_POLICY


WeatherSourceRead = Annotated[
    SingleRunWeatherSource | PreviousRunsWeatherSource, Field(discriminator="product")
]


class WeatherInput(Schema):
    source_id: SourceId
    forecast_offset_days: int | None = Field(default=None, strict=True, ge=1, le=7)
    available_at_estimate: UTCDateTime | None = None


class WeatherProvenance(Schema):
    sources: list[WeatherSourceRead] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        ids = [source.source_id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("Weather source IDs must be unique within a series")
        self.sources.sort(key=lambda source: source.source_id)
        return self

    def by_id(self) -> dict[str, WeatherSourceRead]:
        return {source.source_id: source for source in self.sources}

    def validate_inputs(self, valid_time: datetime, inputs: list[WeatherInput]) -> None:
        sources = self.by_id()
        ids = [item.source_id for item in inputs]
        if len(ids) != len(set(ids)):
            raise ValueError("A weather source can only be referenced once per forecast hour")
        models = set()
        for item in inputs:
            source = sources.get(item.source_id)
            if source is None:
                raise ValueError("Forecast hour references an unknown weather source")
            model_key = (source.provider, source.model)
            if model_key in models:
                raise ValueError("Use one weather input per provider/model for each forecast hour")
            models.add(model_key)
            if isinstance(source, PreviousRunsWeatherSource):
                if item.forecast_offset_days is None or item.available_at_estimate is None:
                    raise ValueError("Previous Runs requires an offset and availability estimate")
                expected = previous_runs_availability(valid_time, item.forecast_offset_days)
                if item.available_at_estimate != expected:
                    raise ValueError("Availability estimate does not match the declared policy")
            elif item.forecast_offset_days is not None or item.available_at_estimate is not None:
                raise ValueError("Single Run inputs use the source publication timestamp")

    def validate_as_of(self, as_of: datetime, inputs: list[WeatherInput]) -> None:
        sources = self.by_id()
        for item in inputs:
            source = sources[item.source_id]
            if isinstance(source, PreviousRunsWeatherSource):
                if item.available_at_estimate is None or item.available_at_estimate > as_of:
                    raise ValueError("Weather availability estimate is later than as_of")
            elif source.available_at > as_of:
                raise ValueError("Weather was not yet available at as_of")

    def uses_estimates(self) -> bool:
        return any(isinstance(source, PreviousRunsWeatherSource) for source in self.sources)

    def storage_provider(self) -> str:
        return "; ".join(sorted({source.provider for source in self.sources}))

    def storage_run(self) -> str | None:
        # A merged series does not identify a single model cycle.
        if len(self.sources) == 1 and isinstance(self.sources[0], SingleRunWeatherSource):
            return self.sources[0].initialization_time.isoformat()
        return None

    def comparable_inputs(self, inputs: list[WeatherInput]) -> list[dict]:
        sources = self.by_id()
        rows = [
            sources[item.source_id].model_dump(mode="json", exclude={"source_id", "retrieved_at"})
            | item.model_dump(mode="json", exclude={"source_id"})
            for item in inputs
        ]
        return sorted(rows, key=lambda row: (row["provider"], row["model"]))
