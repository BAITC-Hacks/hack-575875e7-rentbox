import csv
import hashlib
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event, RLock
from uuid import uuid4

from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.integrations.forecasting import AgentContext, ForecastEngine
from backend.app.integrations.storage import INTERRUPTED, JobStore
from backend.app.schemas.common import ErrorDetail
from backend.app.schemas.forecast import (
    AgentResult,
    AgentUpdate,
    ForecastRunCreate,
    ForecastRunRead,
    ReplayAccepted,
    ReplayCreate,
    ReplayRead,
    RunAccepted,
)
from backend.app.services.data import DataService
from backend.app.services.turbines import TurbineService

logger = logging.getLogger(__name__)


class ForecastService:
    def __init__(
        self,
        settings: Settings,
        turbines: TurbineService,
        data: DataService,
        store: JobStore,
        engine: ForecastEngine | None,
    ):
        self.settings = settings
        self.turbines = turbines
        self.data = data
        self.store = store
        self.engine = engine
        self._stopping = Event()
        self._admission = RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rentbox-agent")

    def close(self) -> None:
        with self._admission:
            self._stopping.set()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self.store.interrupt_pending()

    def _require_ready(self, turbine_ids: list[int]) -> None:
        if self._stopping.is_set():
            raise AppError(503, "SERVER_STOPPING", "Сервер останавливается.", retryable=True)
        for turbine_id in turbine_ids:
            self.turbines.get(turbine_id)
        if self.settings.missing_time_settings:
            raise AppError(
                409,
                "CONFIGURATION_REQUIRED",
                "Подтвердите настройки времени: " + ", ".join(self.settings.missing_time_settings),
            )
        if self.engine is None:
            raise AppError(503, "AGENT_NOT_CONFIGURED", "Модуль агента ещё не подключён.")
        self.data.require_current_audit()

    def _key(self, request: ForecastRunCreate) -> str:
        content = {
            "request": request.model_dump(mode="json", exclude={"refresh_weather"}),
            "source_timezone": self.settings.source_timezone,
            "timestamp_meaning": self.settings.timestamp_meaning,
        }
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def _new_job(self, request: ForecastRunCreate):
        if self.engine is None:
            raise RuntimeError("Agent is not configured")
        state = ForecastRunRead(
            run_id=f"run_{uuid4().hex}",
            agent_mode=self.engine.mode,
            **request.model_dump(exclude={"refresh_weather"}),
        )
        return state, request, self._key(request)

    def create(self, request: ForecastRunCreate) -> RunAccepted:
        with self._admission:
            self._require_ready(request.turbine_ids)
            job = self._new_job(request)
            self.store.create([job], self.settings.max_pending_runs)
            try:
                self._executor.submit(self._execute, job[0].run_id)
            except RuntimeError:
                self.store.fail(job[0].run_id, INTERRUPTED)
                raise AppError(
                    503, "SERVER_STOPPING", "Сервер останавливается.", retryable=True
                ) from None
        return RunAccepted(run_id=job[0].run_id)

    def create_replay(self, request: ReplayCreate) -> ReplayAccepted:
        if request.total_runs > self.settings.max_replay_runs:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                f"За один replay допускается до {self.settings.max_replay_runs} запусков.",
            )
        with self._admission:
            self._require_ready(request.turbine_ids)
            jobs = [
                self._new_job(
                    ForecastRunCreate(
                        as_of=request.first_as_of + timedelta(hours=i * request.step_hours),
                        horizon_hours=request.horizon_hours,
                        turbine_ids=request.turbine_ids,
                    )
                )
                for i in range(request.total_runs)
            ]
            replay = ReplayRead(
                replay_id=f"replay_{uuid4().hex}",
                total_runs=len(jobs),
                run_ids=[job[0].run_id for job in jobs],
            )
            self.store.create(jobs, self.settings.max_pending_runs, replay)
            try:
                self._executor.submit(self._execute_replay, replay.replay_id)
            except RuntimeError:
                for run_id in replay.run_ids:
                    self.store.fail(run_id, INTERRUPTED)
                self.store.update_replay(replay.replay_id, finished=True)
                raise AppError(
                    503, "SERVER_STOPPING", "Сервер останавливается.", retryable=True
                ) from None
        return ReplayAccepted(replay_id=replay.replay_id)

    def _emit(self, run_id: str, update: AgentUpdate) -> None:
        if self._stopping.is_set():
            raise AppError(503, INTERRUPTED.code, INTERRUPTED.message, retryable=True)
        self.store.progress(run_id, AgentUpdate.model_validate(update))

    def _execute(self, run_id: str) -> None:
        try:
            if self._stopping.is_set():
                self.store.fail(run_id, INTERRUPTED)
                return
            request = self.store.get_request(run_id)
            self._emit(
                run_id,
                AgentUpdate(
                    stage="validate",
                    progress=0.02,
                    message="Проверка запроса, настроек времени и исходных файлов.",
                    tool="backend",
                ),
            )
            self._require_ready(request.turbine_ids)
            previous = self.store.previous(self._key(request))
            context = AgentContext(
                run_id=run_id,
                input_dir=self.settings.input_dir,
                source_timezone=self.settings.source_timezone,
                timestamp_meaning=self.settings.timestamp_meaning,
                turbines=tuple(self.turbines.get(t) for t in request.turbine_ids),
                previous=previous[1] if previous else None,
                previous_input_sha256=previous[2] if previous else None,
                emit=lambda update: self._emit(run_id, update),
                cancelled=self._stopping.is_set,
            )
            output = AgentResult.model_validate(self.engine.run(request, context))
            output.validate_for(request)
            self._emit(
                run_id,
                AgentUpdate(
                    stage="review",
                    progress=0.98,
                    message="Проверены горизонт, диапазон мощности и время доступности данных.",
                    tool="backend",
                ),
            )
            self.store.complete(run_id, output, previous)
        except AppError as exc:
            self.store.fail(run_id, exc.error)
        except (ValidationError, ValueError) as exc:
            logger.warning("Invalid agent result for %s: %s", run_id, exc)
            self.store.fail(
                run_id,
                ErrorDetail(
                    code="DATA_QUALITY_ERROR",
                    message="Результат агента не прошёл проверку данных и временных ограничений.",
                ),
            )
        except Exception:
            logger.exception("Agent execution failed for %s", run_id)
            self.store.fail(
                run_id,
                ErrorDetail(
                    code="MODEL_ERROR",
                    message="Ошибка выполнения модуля агента.",
                ),
            )

    def _execute_replay(self, replay_id: str) -> None:
        replay = self.store.get_replay(replay_id)
        try:
            self.store.update_replay(replay_id)
            for run_id in replay.run_ids:
                self._execute(run_id)
                self.store.update_replay(replay_id)
        except Exception:
            logger.exception("Replay execution failed for %s", replay_id)
            error = ErrorDetail(
                code="INTERNAL_ERROR", message="Воспроизведение прервано внутренней ошибкой."
            )
            for run_id in replay.run_ids:
                self.store.fail(run_id, error)
        finally:
            self.store.update_replay(replay_id, finished=True)

    def csv(self, run_id: str) -> str:
        result = self.store.get_result(run_id).model_dump(mode="json")
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            [
                "run_id",
                "as_of",
                "turbine_id",
                "valid_time",
                "lead_hour",
                "predicted_power",
                "weather_initialization_time",
                "weather_available_at",
                "model_version",
            ]
        )
        for series in result["series"]:
            for point in series["points"]:
                writer.writerow(
                    [
                        result["run_id"],
                        result["as_of"],
                        series["turbine_id"],
                        point["valid_time"],
                        point["lead_hour"],
                        point["predicted_power"],
                        series["weather"]["initialization_time"],
                        series["weather"]["available_at"],
                        result["model_version"],
                    ]
                )
        return stream.getvalue()
