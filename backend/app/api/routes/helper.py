from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request

from backend.app.api.deps import ForecastServiceDep
from backend.app.schemas.helper import HelpAnswer, HelpRequest, HelpStatus
from backend.app.services.helper import HelperSettings, answer_help, helper_status

router = APIRouter(prefix="/help", tags=["help"])


@router.get("/status", response_model=HelpStatus)
def status():
    return helper_status()


@router.post("/chat", response_model=HelpAnswer)
def chat(payload: HelpRequest, request: Request, service: ForecastServiceDep):
    # ChatGPT/Codex mode is only for this machine; production uses the API key.
    try:
        local_account = HelperSettings().helper_auth_mode == "chatgpt"
    except ValueError:
        local_account = False
    if local_account:
        origin = request.headers.get("origin")
        local_hosts = {"127.0.0.1", "::1", "localhost"}
        if (
            request.client is None
            or request.client.host not in local_hosts
            or (origin and urlsplit(origin).hostname not in local_hosts)
        ):
            raise HTTPException(403, "Вход ChatGPT доступен только для локальной проверки.")
    return answer_help(payload, service)
