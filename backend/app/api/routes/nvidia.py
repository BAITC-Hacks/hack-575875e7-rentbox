from fastapi import APIRouter
from pydantic import BaseModel
from src.nvidia_api import Explanation, NvidiaClient, NvidiaError, NvidiaSettings, explain_forecast

from backend.app.api.deps import ForecastServiceDep
from backend.app.core.errors import AppError

router = APIRouter(tags=["nvidia"])


class NvidiaStatus(BaseModel):
    enabled: bool
    configured: bool
    model: str
    purpose: str = "Пояснения и рекомендации; обучение модели ВЭС выполняется на CPU/CUDA/Brev."


def read_settings() -> NvidiaSettings:
    try:
        return NvidiaSettings()
    except ValueError:
        raise AppError(
            409, "CONFIGURATION_REQUIRED", "Проверьте настройки NVIDIA в .env."
        ) from None


@router.get("/integrations/nvidia", response_model=NvidiaStatus)
def status():
    settings = read_settings()
    return NvidiaStatus(
        enabled=settings.enabled, configured=settings.configured, model=settings.model
    )


@router.post("/integrations/nvidia/check", response_model=Explanation)
def check():
    settings = read_settings()
    if not settings.enabled or not settings.configured:
        raise AppError(
            409, "CONFIGURATION_REQUIRED", "Задайте NVIDIA_ENABLED=true и NVIDIA_API_KEY."
        )
    try:
        reply = NvidiaClient(settings).chat(
            "Ответь кратко по-русски.", {"question": "Соединение работает?"}
        )
    except NvidiaError as error:
        raise AppError(503, "NVIDIA_UNAVAILABLE", str(error)) from None
    return Explanation(provider="nvidia", model=settings.model, text=reply)


@router.post("/agent/runs/{run_id}/explanation", response_model=Explanation)
def explanation(run_id: str, service: ForecastServiceDep):
    return explain_forecast(service.store.get_result(run_id))
