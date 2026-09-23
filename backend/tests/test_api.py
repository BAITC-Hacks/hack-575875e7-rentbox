import pytest


def test_health_and_read_only_catalog(client):
    assert client.get("/api/health").json() == {
        "status": "ok",
        "agent_configured": False,
        "time_configuration_ready": True,
        "turbines_count": 1,
    }
    catalog = client.get("/api/turbines").json()
    assert catalog["items"][0]["id"] == 1
    assert client.post("/api/turbines", json={}).status_code == 405


def test_unknown_route_is_explicit(client):
    response = client.get("/api/unknown")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"


@pytest.mark.parametrize("suffix", ["", "/forecast"])
def test_missing_run_is_not_a_fake_success(client, suffix):
    response = client.get("/api/agent/runs/missing" + suffix)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_create_forecast_without_engine(client):
    response = client.post(
        "/api/agent/runs",
        json={"turbine_ids": [1], "as_of": "2026-01-31T00:00:00Z", "horizon_hours": 48},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AGENT_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "changes",
    [
        {"as_of": "2026-01-31T00:00:00"},
        {"turbine_ids": [1, 1]},
        {"horizon_hours": 72},
        {"unrecognized_field": True},
    ],
)
def test_invalid_forecast_inputs(client, changes):
    payload = {
        "turbine_ids": [1],
        "as_of": "2026-01-31T00:00:00Z",
        "horizon_hours": 48,
    } | changes
    response = client.post("/api/agent/runs", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_cors_and_documented_contract(client):
    response = client.options(
        "/api/agent/runs",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    schema = client.get("/openapi.json").json()
    route = schema["paths"]["/api/agent/runs"]["post"]
    assert set(route["responses"]) >= {"202", "422", "503"}
