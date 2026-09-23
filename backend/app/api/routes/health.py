from typing import Literal

from fastapi import APIRouter, Request

from backend.app.schemas.common import Schema

router = APIRouter(tags=["health"])


class HealthResponse(Schema):
    status: Literal["ok"] = "ok"
    agent_configured: bool
    time_configuration_ready: bool
    turbines_count: int


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    request.app.state.store.ping()
    return HealthResponse(
        agent_configured=request.app.state.forecasts.engine is not None,
        time_configuration_ready=not request.app.state.settings.missing_time_settings,
        turbines_count=len(request.app.state.turbines.list().items),
    )
