from fastapi import APIRouter

from backend.app.api.deps import ForecastServiceDep
from backend.app.schemas.helper import HelpAnswer, HelpRequest, HelpStatus
from backend.app.services.helper import answer_help, helper_status

router = APIRouter(prefix="/help", tags=["help"])


@router.get("/status", response_model=HelpStatus)
def status():
    return helper_status()


@router.post("/chat", response_model=HelpAnswer)
def chat(payload: HelpRequest, service: ForecastServiceDep):
    return answer_help(payload, service)
