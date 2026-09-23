from fastapi import APIRouter

from backend.app.api.deps import TurbineServiceDep
from backend.app.schemas.turbine import TurbineList

router = APIRouter(prefix="/turbines", tags=["turbines"])


@router.get("", response_model=TurbineList)
def list_turbines(service: TurbineServiceDep):
    return service.list()
