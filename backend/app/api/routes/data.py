from fastapi import APIRouter

from backend.app.api.deps import DataServiceDep
from backend.app.schemas.data import DataSummary

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/summary", response_model=DataSummary)
def summary(service: DataServiceDep):
    return service.summary()
