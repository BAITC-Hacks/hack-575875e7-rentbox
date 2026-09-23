from datetime import date as Date
from typing import Literal

from pydantic import Field, field_validator

from backend.app.schemas.common import Schema
from backend.app.schemas.forecast import ForecastHorizon, TurbineIds

HelpView = Literal["overview", "forecast", "agent", "sources", "history"]


class HelpMessage(Schema):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=3000)


class HelpContext(Schema):
    view: HelpView = "overview"
    mode: Literal["forecast", "simulation"] = "forecast"
    locale: Literal["ru", "en", "kk"] = "ru"
    date: Date | None = None
    horizon_hours: ForecastHorizon = 48
    simulation_hours: int | None = Field(default=None, strict=True, ge=1, le=10000)
    turbine_ids: TurbineIds = Field(default_factory=lambda: [1, 2])


class HelpRequest(Schema):
    message: str = Field(min_length=1, max_length=2000)
    history: list[HelpMessage] = Field(default_factory=list, max_length=8)
    run_id: str | None = Field(default=None, pattern=r"^run_[a-f0-9]{32}$")
    context: HelpContext = Field(default_factory=HelpContext)

    @field_validator("message")
    @classmethod
    def nonempty_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Введите вопрос")
        return value.strip()


class HelpSource(Schema):
    id: str
    title: str
    view: HelpView | None = None


class HelpAction(Schema):
    type: Literal["navigate", "download_csv"]
    label: str
    view: HelpView | None = None
    run_id: str | None = None


class HelpAnswer(Schema):
    provider: Literal["openai", "local_help"]
    model: str | None = None
    text: str
    sources: list[HelpSource]
    actions: list[HelpAction]
    warning: str | None = None
    prompt_version: str


class HelpStatus(Schema):
    provider: Literal["openai"] = "openai"
    model: Literal["gpt-6-astra"] = "gpt-6-astra"
    enabled: bool
    configured: bool
    available: bool
    prompt_version: str


class HelpGeneration(Schema):
    text: str = Field(min_length=1, max_length=3000)
    source_ids: list[str] = Field(min_length=1, max_length=5)
    action_ids: list[str] = Field(max_length=3)
