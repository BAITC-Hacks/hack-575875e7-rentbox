import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.router import router
from backend.app.core.config import Settings
from backend.app.core.errors import register_error_handlers
from backend.app.integrations.forecasting import ForecastEngine, load_engine
from backend.app.integrations.storage import JobStore
from backend.app.services.data import DataService
from backend.app.services.forecasts import ForecastService
from backend.app.services.turbines import TurbineService


def create_app(
    settings: Settings | None = None,
    *,
    engine: ForecastEngine | None = None,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        turbines = TurbineService(settings.turbines_file)
        data = DataService(settings)
        agent = engine if engine is not None else load_engine(settings.agent_factory)
        store = JobStore(settings.database_path, settings.max_events_per_run)
        service = ForecastService(settings, turbines, data, store, agent)
        application.state.settings = settings
        application.state.turbines = turbines
        application.state.data = data
        application.state.store = store
        application.state.forecasts = service
        try:
            yield
        finally:
            try:
                await asyncio.to_thread(service.close)
            finally:
                store.close()

    application = FastAPI(
        title=settings.app_name,
        version="0.3.0",
        description=(
            "API дашборда ВЭС: исторические прогнозы, состояние агента и CSV. "
            "Расчёты доступны после подключения агента и подтверждения настроек времени."
        ),
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["Location", "Content-Disposition"],
    )
    register_error_handlers(application)
    application.include_router(router)
    return application


app = create_app()
