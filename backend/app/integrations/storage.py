from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from backend.app.core.errors import AppError
from backend.app.schemas.common import ErrorDetail
from backend.app.schemas.forecast import (
    AgentEvent,
    AgentResult,
    AgentUpdate,
    ForecastRead,
    ForecastRunCreate,
    ForecastRunRead,
    ForecastSeries,
    ReplayRead,
)
from src.storage import ForecastRow, ForecastStore

API_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_runs (
    run_id VARCHAR PRIMARY KEY,
    request_key VARCHAR NOT NULL,
    request JSON NOT NULL,
    state JSON NOT NULL,
    status VARCHAR NOT NULL,
    result JSON,
    input_sha256 VARCHAR,
    created_at TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS api_replays (
    replay_id VARCHAR PRIMARY KEY,
    state JSON NOT NULL,
    status VARCHAR NOT NULL
);
"""
INTERRUPTED = ErrorDetail(
    code="JOB_INTERRUPTED",
    message="Выполнение прервано остановкой сервера. Создайте новый запуск.",
    retryable=True,
)
PreviousResult = tuple[ForecastRunRead, ForecastRead, str]


def comparable_result(result: AgentResult | ForecastRead) -> dict:
    """Ignore download timestamps and prose when checking reproducible numeric output."""
    series = []
    for item in sorted(result.series, key=lambda value: value.turbine_id):
        series.append(
            {
                "turbine_id": item.turbine_id,
                "points": [
                    point.model_dump(mode="json", exclude={"weather_inputs"})
                    | {"weather_inputs": item.weather.comparable_inputs(point.weather_inputs)}
                    for point in item.points
                ],
            }
        )
    return {
        "model_version": result.model_version,
        "training_data_available_until": result.training_data_available_until,
        "series": series,
    }


def event(update: AgentUpdate) -> AgentEvent:
    return AgentEvent(
        id=f"event_{uuid4().hex}",
        timestamp=datetime.now(UTC),
        **update.model_dump(exclude={"progress", "agent_mode"}),
    )


class JobStore:
    """A single process owns this connection. Every access is serialized by the lock."""

    def __init__(self, path: Path, max_events: int):
        self._lock = RLock()
        self.max_events = max_events
        self.forecasts = ForecastStore(path)
        self.connection = self.forecasts.connection
        try:
            self.connection.execute(API_SCHEMA)
            self.interrupt_pending()
        except BaseException:
            self.forecasts.close()
            raise

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            self.connection.execute("BEGIN TRANSACTION")
            try:
                yield
                self.connection.execute("COMMIT")
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise

    def close(self) -> None:
        with self._lock:
            self.forecasts.close()

    def ping(self) -> None:
        with self._lock:
            self.connection.execute("SELECT 1").fetchone()

    def create(
        self,
        jobs: list[tuple[ForecastRunRead, ForecastRunCreate, str]],
        max_pending: int,
        replay: ReplayRead | None = None,
    ) -> None:
        with self.transaction():
            count = self.connection.execute(
                "SELECT count(*) FROM api_runs WHERE status IN ('queued', 'running')"
            ).fetchone()[0]
            if count + len(jobs) > max_pending:
                raise AppError(429, "QUEUE_FULL", "Очередь заполнена.", retryable=True)
            for state, request, key in jobs:
                self.connection.execute(
                    """INSERT INTO api_runs
                    (run_id, request_key, request, state, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        state.run_id,
                        key,
                        request.model_dump_json(),
                        state.model_dump_json(),
                        state.status,
                        datetime.now(UTC).replace(tzinfo=None),
                    ],
                )
            if replay:
                self.connection.execute(
                    "INSERT INTO api_replays VALUES (?, ?, ?)",
                    [replay.replay_id, replay.model_dump_json(), replay.status],
                )

    def list_runs(self, limit: int = 100) -> list[ForecastRunRead]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT state FROM api_runs ORDER BY created_at DESC, run_id DESC LIMIT ?",
                [limit],
            ).fetchall()
        return [ForecastRunRead.model_validate_json(row[0]) for row in rows]

    def get_run(self, run_id: str) -> ForecastRunRead:
        with self._lock:
            row = self.connection.execute(
                "SELECT state FROM api_runs WHERE run_id = ?", [run_id]
            ).fetchone()
        if row is None:
            raise AppError(404, "RUN_NOT_FOUND", "Запуск не найден.")
        return ForecastRunRead.model_validate_json(row[0])

    def get_request(self, run_id: str) -> ForecastRunCreate:
        with self._lock:
            row = self.connection.execute(
                "SELECT request FROM api_runs WHERE run_id = ?", [run_id]
            ).fetchone()
        if row is None:
            raise AppError(404, "RUN_NOT_FOUND", "Запуск не найден.")
        return ForecastRunCreate.model_validate_json(row[0])

    def get_result(self, run_id: str) -> ForecastRead:
        with self._lock:
            state = self.get_run(run_id)
            if state.status != "completed":
                raise AppError(
                    409,
                    "RESULT_NOT_READY",
                    "Запуск завершился ошибкой."
                    if state.status == "failed"
                    else "Результат ещё не готов.",
                    retryable=state.status in ("queued", "running"),
                )
            row = self.connection.execute(
                "SELECT result FROM api_runs WHERE run_id = ?", [run_id]
            ).fetchone()
        return ForecastRead.model_validate_json(row[0])

    def previous(self, request_key: str) -> PreviousResult | None:
        with self._lock:
            row = self.connection.execute(
                """SELECT state, result, input_sha256 FROM api_runs
                WHERE request_key = ? AND status = 'completed'
                ORDER BY created_at DESC, run_id DESC LIMIT 1""",
                [request_key],
            ).fetchone()
        if row is None:
            return None
        return (
            ForecastRunRead.model_validate_json(row[0]),
            ForecastRead.model_validate_json(row[1]),
            row[2],
        )

    def _save_run(self, state: ForecastRunRead) -> None:
        self.connection.execute(
            "UPDATE api_runs SET state = ?, status = ? WHERE run_id = ?",
            [state.model_dump_json(), state.status, state.run_id],
        )

    def progress(self, run_id: str, update: AgentUpdate) -> None:
        with self._lock:
            state = self.get_run(run_id)
            if state.status not in ("queued", "running"):
                return
            if len(state.events) >= self.max_events:
                raise AppError(500, "AGENT_LIMIT_EXCEEDED", "Превышен лимит событий агента.")
            state.status = "running"
            if update.agent_mode is not None:
                state.agent_mode = update.agent_mode
            state.stage = update.stage
            state.progress = max(state.progress, min(update.progress, 0.99))
            state.events.append(event(update))
            if update.level == "warning" and update.message not in state.warnings:
                state.warnings.append(update.message)
            self._save_run(state)

    def fail(self, run_id: str, error: ErrorDetail) -> None:
        with self._lock:
            state = self.get_run(run_id)
            if state.status in ("completed", "failed"):
                return
            state.status = "failed"
            state.error = error
            state.events.append(
                event(
                    AgentUpdate(
                        stage=state.stage,
                        progress=state.progress,
                        level="error",
                        message=error.message,
                    )
                )
            )
            self._save_run(state)

    def complete(self, run_id: str, output: AgentResult, previous: PreviousResult | None) -> None:
        request = self.get_request(run_id)
        output.validate_for(request)
        with self.transaction():
            state = self.get_run(run_id)
            if state.status != "running":
                raise RuntimeError("Only a running job can save results")
            reuse = previous is not None and previous[2] == output.input_sha256
            if reuse:
                old_state, old_result, _ = previous
                if comparable_result(old_result) != comparable_result(output):
                    raise AppError(
                        500,
                        "DATA_QUALITY_ERROR",
                        "Одинаковый хеш входов дал разные прогнозы или происхождение данных.",
                    )
                result = old_result.model_copy(update={"run_id": run_id})
                state.revision = old_state.revision
                state.reused_run_id = old_state.reused_run_id or old_state.run_id
            else:
                series = []
                for computed in output.series:
                    storage_id = self.forecasts.record_run(
                        issued_at=request.as_of.replace(tzinfo=None),
                        turbine_id=computed.turbine_id,
                        weather_source=computed.weather.storage_provider(),
                        weather_run=computed.weather.storage_run(),
                        model_name=output.model_name,
                        model_version=output.model_version,
                        horizon_hours=request.horizon_hours,
                        trigger="weather_update" if previous else "manual",
                        note=f"api_run_id={run_id}; weather provenance in api_runs.result",
                    )
                    self.forecasts.record_forecast(
                        storage_id,
                        [
                            ForecastRow(
                                point.valid_time.replace(tzinfo=None), point.predicted_power
                            )
                            for point in computed.points
                        ],
                    )
                    series.append(
                        ForecastSeries(
                            **computed.model_dump(),
                            storage_run_id=storage_id,
                        )
                    )
                result = ForecastRead(
                    run_id=run_id,
                    as_of=request.as_of,
                    horizon_hours=request.horizon_hours,
                    model_version=output.model_version,
                    training_data_available_until=output.training_data_available_until,
                    series=series,
                    analysis=output.analysis,
                )
                if previous:
                    state.revision = previous[0].revision + 1
                    state.supersedes_run_id = previous[0].run_id
            state.status = "completed"
            state.agent_mode = output.agent_mode
            state.stage = "save"
            state.progress = 1
            state.warnings = list(dict.fromkeys(state.warnings + result.analysis.warnings))
            state.events.append(
                event(
                    AgentUpdate(
                        stage="save",
                        progress=1,
                        message="Входы не изменились; сохранена ссылка на прежний результат."
                        if reuse
                        else "Прогноз и его происхождение сохранены в DuckDB.",
                        tool="ForecastStore",
                    )
                )
            )
            self._save_run(state)
            self.connection.execute(
                "UPDATE api_runs SET result = ?, input_sha256 = ? WHERE run_id = ?",
                [result.model_dump_json(), output.input_sha256, run_id],
            )

    def get_replay(self, replay_id: str) -> ReplayRead:
        with self._lock:
            row = self.connection.execute(
                "SELECT state FROM api_replays WHERE replay_id = ?", [replay_id]
            ).fetchone()
        if row is None:
            raise AppError(404, "REPLAY_NOT_FOUND", "Воспроизведение не найдено.")
        return ReplayRead.model_validate_json(row[0])

    def update_replay(self, replay_id: str, *, finished: bool = False) -> None:
        with self._lock:
            replay = self.get_replay(replay_id)
            states = [self.get_run(run_id) for run_id in replay.run_ids]
            replay.completed_runs = sum(s.status == "completed" for s in states)
            replay.failed_runs = sum(s.status == "failed" for s in states)
            replay.status = "running"
            if finished:
                replay.status = "failed" if replay.failed_runs else "completed"
                if replay.failed_runs:
                    replay.error = ErrorDetail(
                        code="REPLAY_FAILED",
                        message="Некоторые запуски завершились ошибкой.",
                        retryable=any(s.error and s.error.retryable for s in states),
                    )
            self.connection.execute(
                "UPDATE api_replays SET state = ?, status = ? WHERE replay_id = ?",
                [replay.model_dump_json(), replay.status, replay_id],
            )

    def interrupt_pending(self) -> None:
        with self.transaction():
            rows = self.connection.execute(
                "SELECT run_id FROM api_runs WHERE status IN ('queued', 'running')"
            ).fetchall()
            for (run_id,) in rows:
                self.fail(run_id, INTERRUPTED)
            replays = self.connection.execute(
                "SELECT replay_id FROM api_replays WHERE status IN ('queued', 'running')"
            ).fetchall()
            for (replay_id,) in replays:
                self.update_replay(replay_id, finished=True)
