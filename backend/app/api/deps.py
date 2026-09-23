from typing import Annotated

from fastapi import Depends, Request

from backend.app.services.data import DataService
from backend.app.services.forecasts import ForecastService
from backend.app.services.turbines import TurbineService


def get_turbine_service(request: Request) -> TurbineService:
    return request.app.state.turbines


def get_forecast_service(request: Request) -> ForecastService:
    return request.app.state.forecasts


def get_data_service(request: Request) -> DataService:
    return request.app.state.data


TurbineServiceDep = Annotated[TurbineService, Depends(get_turbine_service)]
ForecastServiceDep = Annotated[ForecastService, Depends(get_forecast_service)]
DataServiceDep = Annotated[DataService, Depends(get_data_service)]
