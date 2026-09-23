from fastapi import APIRouter

from backend.app.api.routes import data, forecasts, health, helper, nvidia, turbines
from backend.app.schemas.common import ErrorResponse

router = APIRouter(
    prefix="/api",
    responses={code: {"model": ErrorResponse} for code in (404, 409, 422, 429, 500, 503)},
)
router.include_router(health.router)
router.include_router(turbines.router)
router.include_router(data.router)
router.include_router(forecasts.router)
router.include_router(nvidia.router)
router.include_router(helper.router)
