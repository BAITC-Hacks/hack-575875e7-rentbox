"""Smoke tests for the forecast history store.

    python -m pytest tests/test_storage.py -q
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.storage import ForecastRow, ForecastStore, StorageError

ISSUED = datetime(2026, 1, 31, 12, 0)


@pytest.fixture()
def store(tmp_path):
    with ForecastStore(tmp_path / "forecasts.duckdb") as opened:
        yield opened


def _hours(issued: datetime, count: int, power: float = 0.4) -> list[ForecastRow]:
    return [
        ForecastRow(issued + timedelta(hours=lead), power, wind_speed=7.0, temperature=-3.0)
        for lead in range(1, count + 1)
    ]


def _run(store: ForecastStore, issued: datetime = ISSUED, **overrides) -> int:
    parameters = {
        "issued_at": issued,
        "turbine_id": 1,
        "weather_source": "open-meteo historical-forecast",
        "weather_run": "previous_day1",
        "model_name": "hist-gradient-boosting",
        "model_version": "v1",
        "horizon_hours": 48,
    }
    parameters.update(overrides)
    return store.record_run(**parameters)


def test_round_trip(store):
    run_id = _run(store)
    assert store.record_forecast(run_id, _hours(ISSUED, 24)) == 24
    assert store.summary() == {"forecast_runs": 1, "forecasts": 24, "actuals": 0}


def test_lead_hours_are_derived(store):
    run_id = _run(store)
    store.record_forecast(run_id, [ForecastRow(ISSUED + timedelta(hours=30), 0.5)])
    assert store.latest(1)["lead_hours"].tolist() == [30]


def test_latest_forecast_wins(store):
    """The later issue replaces the earlier one for the same hour."""
    target = ISSUED + timedelta(hours=40)
    store.record_forecast(_run(store), [ForecastRow(target, 0.30)])
    later = ISSUED + timedelta(hours=24)
    store.record_forecast(_run(store, later, weather_run="previous_day1"), [ForecastRow(target, 0.55)])

    standing = store.latest(1)
    assert len(standing) == 1
    assert standing["predicted_power"].iloc[0] == pytest.approx(0.55)

    revisions = store.revisions(1, target)
    assert revisions["predicted_power"].tolist() == [0.30, 0.55]
    assert revisions["change"].iloc[1] == pytest.approx(0.25)


def test_accuracy_against_measurements(store):
    target = ISSUED + timedelta(hours=12)
    store.record_forecast(_run(store), [ForecastRow(target, 0.60)])
    store.record_actuals(1, [(target, 0.50, 1.0)])

    accuracy = store.accuracy_by_lead()
    assert accuracy["hours"].iloc[0] == 1
    assert accuracy["mae"].iloc[0] == pytest.approx(0.10)
    assert accuracy["bias"].iloc[0] == pytest.approx(0.10)


def test_power_outside_unit_interval_is_rejected(store):
    run_id = _run(store)
    with pytest.raises(StorageError, match=r"\[0, 1\]"):
        store.record_forecast(run_id, [ForecastRow(ISSUED + timedelta(hours=1), 1.4)])


def test_forecast_cannot_address_the_past(store):
    run_id = _run(store)
    with pytest.raises(StorageError, match="cannot address the past"):
        store.record_forecast(run_id, [ForecastRow(ISSUED - timedelta(hours=1), 0.3)])


def test_horizon_is_enforced(store):
    run_id = _run(store, horizon_hours=48)
    with pytest.raises(StorageError, match="beyond the declared horizon"):
        store.record_forecast(run_id, [ForecastRow(ISSUED + timedelta(hours=72), 0.3)])


def test_unknown_turbine_is_rejected(store):
    with pytest.raises(StorageError, match="turbine_id must be one of"):
        _run(store, turbine_id=7)


def test_forecast_needs_an_existing_run(store):
    with pytest.raises(StorageError, match="does not exist"):
        store.record_forecast(999, _hours(ISSUED, 1))


def test_missing_database_reports_how_to_create_it(tmp_path):
    with pytest.raises(StorageError, match="python -m src.storage init"):
        ForecastStore(tmp_path / "absent.duckdb", read_only=True)
