"""MOCK: NVIDIA responses are isolated HTTP fixtures, with no real API key."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from scripts.nvidia_api import training_summary
from src.nvidia_api import NvidiaClient, NvidiaError, NvidiaSettings, explain_forecast


def config(**kwargs):
    return NvidiaSettings(_env_file=None, enabled=True, api_key="test-secret", **kwargs)


def forecast():
    return SimpleNamespace(
        as_of=datetime(2026, 1, 31, 18, tzinfo=UTC),
        horizon_hours=48,
        model_version="test-model",
        analysis=SimpleNamespace(summary="Расчёт модели готов."),
        series=[
            SimpleNamespace(
                turbine_id=1,
                points=[
                    SimpleNamespace(predicted_power=0.1),
                    SimpleNamespace(predicted_power=0.7),
                ],
            )
        ],
    )


def test_disabled_makes_no_request():
    def forbidden(request):
        pytest.fail("Disabled NVIDIA must not make a network request")

    result = explain_forecast(
        forecast(),
        settings=NvidiaSettings(_env_file=None, enabled=False),
        transport=httpx.MockTransport(forbidden),
    )
    assert result.provider == "policy"
    assert result.text == "Расчёт модели готов."


def test_request_and_forecast_are_separate():
    original = forecast()

    def respond(request):
        assert request.url == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret"
        payload = json.loads(request.content)
        data = json.loads(payload["messages"][1]["content"])
        assert data["turbines"][0]["max"] == 0.7
        assert "power" not in data  # no actual target series
        return httpx.Response(200, json={"choices": [{"message": {"content": "Пояснение."}}]})

    result = explain_forecast(original, settings=config(), transport=httpx.MockTransport(respond))
    assert result.provider == "nvidia"
    assert result.text == "Пояснение."
    assert [p.predicted_power for p in original.series[0].points] == [0.1, 0.7]


@pytest.mark.parametrize("status", [302, 401, 403, 404, 429, 500, 503])
def test_provider_errors_are_safe_and_fall_back(status):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status,
            text="provider may echo test-secret",
            headers={"Location": "https://example.com"},
        )
    )
    result = explain_forecast(forecast(), settings=config(), transport=transport)
    assert result.provider == "policy"
    assert result.warning
    assert "test-secret" not in result.model_dump_json()


def test_timeout_falls_back():
    def timeout(request):
        raise httpx.ReadTimeout("private details", request=request)

    result = explain_forecast(forecast(), settings=config(), transport=httpx.MockTransport(timeout))
    assert result.provider == "policy"
    assert "private" not in result.warning


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": {"content": ""}}]}])
def test_invalid_response(body):
    client = NvidiaClient(
        config(), httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    )
    with pytest.raises(NvidiaError, match="некорректный"):
        client.chat("test", {})


def test_key_missing_and_not_exposed_in_repr():
    assert "test-secret" not in repr(config())
    client = NvidiaClient(NvidiaSettings(_env_file=None, enabled=True, api_key=""))
    with pytest.raises(NvidiaError, match="NVIDIA_API_KEY"):
        client.chat("test", {})


def test_dotenv_is_data_not_shell(tmp_path, monkeypatch):
    for name in ("NVIDIA_API_KEY", "NVIDIA_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    path.write_text('NVIDIA_ENABLED=true\nNVIDIA_API_KEY="literal-$(echo injected)"\n')
    settings = NvidiaSettings(_env_file=path)
    assert settings.api_key.get_secret_value() == "literal-$(echo injected)"


def test_training_advice_excludes_january(tmp_path):
    path = tmp_path / "selection.json"
    data = {
        "selection_months": ["2025-11", "2025-12"],
        "january_used_for_search": False,
        "january": {"power": "must not leave"},
        "ranking": [
            {"config": {"family": "tree"}, "metrics": {"mae": 0.2}, "january": "must not leave"}
        ],
    }
    path.write_text(json.dumps(data))
    summary = training_summary(path)
    assert "must not leave" not in json.dumps(summary)
    data["selection_months"].append("2026-01")
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        training_summary(path)


def test_status_never_returns_key(client, monkeypatch):
    from backend.app.api.routes import nvidia

    monkeypatch.setattr(nvidia, "NvidiaSettings", lambda: config())
    response = client.get("/api/integrations/nvidia")
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert "test-secret" not in response.text
