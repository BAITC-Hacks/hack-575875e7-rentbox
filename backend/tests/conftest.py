import json

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app


@pytest.fixture
def settings(tmp_path):
    # MOCK: synthetic coordinates and confirmed UTC apply only to these isolated tests.
    config = tmp_path / "turbines.json"
    config.write_text(
        json.dumps([{"id": 1, "name": "Test turbine", "latitude": 0, "longitude": 0}])
    )
    return Settings(
        _env_file=None,
        turbines_file=config,
        database_path=tmp_path / "test.duckdb",
        agent_factory=None,
        source_timezone="UTC",
        timestamp_meaning="interval_start",
        time_configuration_confirmed=True,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client
