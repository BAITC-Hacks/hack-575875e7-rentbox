from fastapi import APIRouter, Response

from backend.app.api.deps import ForecastServiceDep
from backend.app.schemas.forecast import (
    ForecastRead,
    ForecastRunCreate,
    ForecastRunRead,
    ReplayAccepted,
    ReplayCreate,
    ReplayRead,
    RunAccepted,
)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/runs", response_model=RunAccepted, status_code=202)
def create_run(payload: ForecastRunCreate, response: Response, service: ForecastServiceDep):
    accepted = service.create(payload)
    response.headers["Location"] = f"/api/agent/runs/{accepted.run_id}"
    return accepted


@router.get("/runs/{run_id}", response_model=ForecastRunRead)
def get_run(run_id: str, service: ForecastServiceDep):
    return service.store.get_run(run_id)


@router.get("/runs/{run_id}/forecast", response_model=ForecastRead)
def get_forecast(run_id: str, service: ForecastServiceDep):
    return service.store.get_result(run_id)


@router.get(
    "/runs/{run_id}/forecast.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def get_csv(run_id: str, service: ForecastServiceDep):
    content = service.csv(run_id)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="forecast-{run_id}.csv"'},
    )


@router.post("/replays", response_model=ReplayAccepted, status_code=202)
def create_replay(payload: ReplayCreate, response: Response, service: ForecastServiceDep):
    accepted = service.create_replay(payload)
    response.headers["Location"] = f"/api/agent/replays/{accepted.replay_id}"
    return accepted


@router.get("/replays/{replay_id}", response_model=ReplayRead)
def get_replay(replay_id: str, service: ForecastServiceDep):
    return service.store.get_replay(replay_id)
