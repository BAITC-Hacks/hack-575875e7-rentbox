from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Literal, Protocol

from backend.app.schemas.forecast import (
    AgentMode,
    AgentResult,
    AgentUpdate,
    ForecastRead,
    ForecastRunCreate,
)
from backend.app.schemas.turbine import TurbineRead


@dataclass(frozen=True)
class AgentContext:
    run_id: str
    input_dir: Path
    source_timezone: str
    timestamp_meaning: Literal["interval_start", "interval_end"]
    turbines: tuple[TurbineRead, ...]
    previous: ForecastRead | None
    previous_input_sha256: str | None
    emit: Callable[[AgentUpdate], None]
    cancelled: Callable[[], bool]


class ForecastEngine(Protocol):
    """The agent computes; the API owns the queue and all DuckDB writes."""

    mode: AgentMode

    def run(self, request: ForecastRunCreate, context: AgentContext) -> AgentResult: ...


def load_engine(factory_path: str | None) -> ForecastEngine | None:
    if factory_path is None:
        return None
    module_name, separator, attribute = factory_path.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("RENTBOX_AGENT_FACTORY must have the form package.module:factory")
    factory = getattr(import_module(module_name), attribute)
    engine = factory()
    if getattr(engine, "mode", None) not in ("llm", "policy") or not callable(
        getattr(engine, "run", None)
    ):
        raise TypeError("Agent factory must return a ForecastEngine with mode and run()")
    return engine
