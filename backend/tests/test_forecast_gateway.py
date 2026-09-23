import hashlib
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.core.errors import AppError
from backend.app.main import create_app
from backend.app.schemas.forecast import AgentResult

REQUEST = {"turbine_ids": [1], "as_of": "2026-01-31T05:00:00+05:00", "horizon_hours": 24}


class TestEngine:
    # MOCK: deterministic forecasts exist only at the agent boundary in tests.
    __test__ = False
    mode = "policy"

    def __init__(self, failure=None):
        self.requests = []
        self.failure = failure

    def run(self, request, context):
        self.requests.append(request)
        if self.failure:
            raise self.failure
        return AgentResult(
            agent_mode=self.mode,
            input_sha256=hashlib.sha256(request.model_dump_json().encode()).hexdigest(),
            model_name="test",
            model_version="test-v1",
            training_data_available_until=request.as_of - timedelta(days=1),
            series=[
                {
                    "turbine_id": 1,
                    "points": [
                        {
                            "valid_time": request.as_of + timedelta(hours=lead),
                            "lead_hour": lead,
                            "predicted_power": lead / 100,
                        }
                        for lead in range(1, request.horizon_hours + 1)
                    ],
                    "weather": {
                        "provider": "test",
                        "model": "test",
                        "initialization_time": request.as_of - timedelta(hours=6),
                        "available_at": request.as_of - timedelta(hours=3),
                        "availability_basis": "MOCK test fixture",
                        "retrieved_at": datetime.now(UTC),
                        "sha256": "a" * 64,
                    },
                }
            ],
            analysis={"summary": "MOCK test output", "warnings": []},
        )


def finished(client, url):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = client.get(url).json()
        if state["status"] in ("completed", "failed"):
            return state
        time.sleep(0.01)
    raise AssertionError("Background job did not finish")


def test_forecast_is_forwarded_and_origin_is_normalized(settings):
    engine = TestEngine()
    with TestClient(create_app(settings, engine=engine)) as client:
        response = client.post("/api/agent/runs", json=REQUEST)
        assert response.status_code == 202
        assert response.json()["status"] == "queued"
        location = response.headers["location"]
        assert finished(client, location)["status"] == "completed"
        result = client.get(location + "/forecast").json()
        assert result["as_of"] == "2026-01-31T00:00:00Z"
        assert len(result["series"][0]["points"]) == 24
    assert engine.requests[0].as_of == datetime(2026, 1, 31, tzinfo=UTC)


@pytest.mark.parametrize(
    "failure,code",
    [
        (RuntimeError("private internal details"), "MODEL_ERROR"),
        (AppError(503, "WEATHER_UNAVAILABLE", "Нет допустимого выпуска."), "WEATHER_UNAVAILABLE"),
        (ValueError("private invalid output"), "DATA_QUALITY_ERROR"),
    ],
)
def test_agent_failures_are_translated(settings, failure, code):
    with TestClient(create_app(settings, engine=TestEngine(failure))) as client:
        response = client.post("/api/agent/runs", json=REQUEST)
        state = finished(client, response.headers["location"])
        assert state["status"] == "failed"
        assert state["error"]["code"] == code
        assert "private" not in str(state)


def test_agent_timeout_is_retryable(settings):
    failure = AppError(
        504,
        "WEATHER_UNAVAILABLE",
        "Источник не ответил вовремя.",
        retryable=True,
    )
    with TestClient(create_app(settings, engine=TestEngine(failure))) as client:
        response = client.post("/api/agent/runs", json=REQUEST)
        state = finished(client, response.headers["location"])
        assert state["error"]["retryable"] is True
        assert state["status"] == "failed"
