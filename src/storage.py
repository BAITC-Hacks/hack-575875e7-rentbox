"""Store the agent's forecast history in a single DuckDB file.

The agent re-forecasts the same hour several times: once at a 48 hour lead,
again at 24 hours, and again whenever the weather provider publishes a newer
run. Every one of those attempts is kept, so a revision can be compared with
the one it replaced and with the measured value when one exists.

No server is required. The database is one file, rebuilt from the recorded
runs, so a reviewer only needs Python and duckdb.

    python -m src.storage init
    python -m src.storage summary
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

import duckdb

DEFAULT_PATH = Path("data/forecasts.duckdb")
TURBINES = (1, 2)
TRIGGERS = ("scheduled", "weather_update", "backfill", "manual")

SCHEMA = """
CREATE SEQUENCE IF NOT EXISTS run_ids START 1;

-- One pass of the agent loop: fetch weather, prepare, predict, analyse.
CREATE TABLE IF NOT EXISTS forecast_runs (
    run_id         BIGINT PRIMARY KEY,
    issued_at      TIMESTAMP NOT NULL,  -- the moment the decision is made
    created_at     TIMESTAMP NOT NULL,  -- when the row was actually written
    turbine_id     INTEGER  NOT NULL,
    weather_source VARCHAR  NOT NULL,   -- e.g. open-meteo historical-forecast
    weather_run    VARCHAR,             -- which published run: previous_day1, ...
    model_name     VARCHAR  NOT NULL,
    model_version  VARCHAR  NOT NULL,
    horizon_hours  INTEGER  NOT NULL,
    trigger        VARCHAR  NOT NULL,
    status         VARCHAR  NOT NULL,
    note           VARCHAR
);

-- Hourly values produced by one run.
CREATE TABLE IF NOT EXISTS forecasts (
    run_id          BIGINT    NOT NULL,
    turbine_id      INTEGER   NOT NULL,
    target_ts       TIMESTAMP NOT NULL,
    lead_hours      INTEGER   NOT NULL,
    predicted_power DOUBLE    NOT NULL,
    wind_speed      DOUBLE,
    temperature     DOUBLE,
    PRIMARY KEY (run_id, turbine_id, target_ts)
);

-- Measured hourly power, available for the training history only.
CREATE TABLE IF NOT EXISTS actuals (
    turbine_id   INTEGER   NOT NULL,
    target_ts    TIMESTAMP NOT NULL,
    actual_power DOUBLE    NOT NULL,
    coverage     DOUBLE    NOT NULL,  -- share of the hour with measurements
    PRIMARY KEY (turbine_id, target_ts)
);

-- The forecast that stands for each hour: newest issue wins.
CREATE OR REPLACE VIEW latest_forecasts AS
SELECT f.*, r.issued_at, r.weather_run, r.model_version
FROM forecasts f
JOIN forecast_runs r USING (run_id)
QUALIFY row_number() OVER (
    PARTITION BY f.turbine_id, f.target_ts ORDER BY r.issued_at DESC, f.run_id DESC
) = 1;

-- How the forecast for one hour moved between successive runs.
CREATE OR REPLACE VIEW forecast_revisions AS
SELECT
    f.turbine_id,
    f.target_ts,
    r.issued_at,
    f.lead_hours,
    f.predicted_power,
    f.predicted_power - lag(f.predicted_power) OVER w AS change,
    r.weather_run,
    r.trigger
FROM forecasts f
JOIN forecast_runs r USING (run_id)
WINDOW w AS (PARTITION BY f.turbine_id, f.target_ts ORDER BY r.issued_at, f.run_id);

-- Error of the standing forecast, for hours where a measurement exists.
CREATE OR REPLACE VIEW forecast_accuracy AS
SELECT
    l.turbine_id,
    l.target_ts,
    l.lead_hours,
    l.predicted_power,
    a.actual_power,
    a.coverage,
    l.predicted_power - a.actual_power AS error
FROM latest_forecasts l
JOIN actuals a USING (turbine_id, target_ts);
"""


class StorageError(RuntimeError):
    """Raised with a readable message instead of a driver traceback."""


@dataclass(frozen=True)
class ForecastRow:
    """One hour of one forecast."""

    target_ts: datetime
    predicted_power: float
    wind_speed: float | None = None
    temperature: float | None = None


class ForecastStore:
    """Thin wrapper over the DuckDB file holding the forecast history."""

    def __init__(self, path: Path | str = DEFAULT_PATH, *, read_only: bool = False) -> None:
        self.path = Path(path)
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.path.exists():
            raise StorageError(
                f"Database {self.path} not found. Create it with: python -m src.storage init"
            )
        self.connection = duckdb.connect(str(self.path), read_only=read_only)
        if not read_only:
            self.connection.execute(SCHEMA)

    # -- writing ---------------------------------------------------------

    def record_run(
        self,
        *,
        issued_at: datetime,
        turbine_id: int,
        weather_source: str,
        model_name: str,
        model_version: str,
        horizon_hours: int,
        weather_run: str | None = None,
        trigger: str = "scheduled",
        status: str = "ok",
        note: str | None = None,
    ) -> int:
        """Register one pass of the agent loop and return its run_id."""
        _check_turbine(turbine_id)
        if trigger not in TRIGGERS:
            raise StorageError(f"Unknown trigger {trigger!r}; expected one of {TRIGGERS}")
        if horizon_hours <= 0:
            raise StorageError(f"horizon_hours must be positive, got {horizon_hours}")
        run_id = self.connection.execute("SELECT nextval('run_ids')").fetchone()[0]
        self.connection.execute(
            """
            INSERT INTO forecast_runs VALUES
            (?, ?, current_localtimestamp(), ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run_id,
                issued_at,
                turbine_id,
                weather_source,
                weather_run,
                model_name,
                model_version,
                horizon_hours,
                trigger,
                status,
                note,
            ],
        )
        return int(run_id)

    def record_forecast(self, run_id: int, rows: Iterable[ForecastRow]) -> int:
        """Attach hourly values to a run. Returns how many rows were stored."""
        run = self.connection.execute(
            "SELECT issued_at, turbine_id, horizon_hours FROM forecast_runs WHERE run_id = ?",
            [run_id],
        ).fetchone()
        if run is None:
            raise StorageError(f"Run {run_id} does not exist; call record_run first")
        issued_at, turbine_id, horizon_hours = run

        payload = []
        for row in rows:
            if not 0.0 <= row.predicted_power <= 1.0:
                raise StorageError(
                    "predicted_power is a normalised value in [0, 1]; "
                    f"got {row.predicted_power} for {row.target_ts}"
                )
            lead = (row.target_ts - issued_at).total_seconds() / 3600
            if lead <= 0:
                raise StorageError(
                    f"target_ts {row.target_ts} is not after issued_at {issued_at}; "
                    "a forecast cannot address the past"
                )
            if lead > horizon_hours:
                raise StorageError(
                    f"target_ts {row.target_ts} is {lead:.0f} h ahead, "
                    f"beyond the declared horizon of {horizon_hours} h"
                )
            payload.append(
                (
                    run_id,
                    turbine_id,
                    row.target_ts,
                    round(lead),
                    row.predicted_power,
                    row.wind_speed,
                    row.temperature,
                )
            )
        if not payload:
            raise StorageError(f"Run {run_id} carries no forecast rows")
        self.connection.executemany(
            "INSERT OR REPLACE INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?)", payload
        )
        return len(payload)

    def record_actuals(self, turbine_id: int, rows: Sequence[tuple[datetime, float, float]]) -> int:
        """Store measured hourly power as (target_ts, actual_power, coverage)."""
        _check_turbine(turbine_id)
        payload = []
        for target_ts, actual_power, coverage in rows:
            if not 0.0 <= actual_power <= 1.0:
                raise StorageError(
                    f"actual_power must be in [0, 1]; got {actual_power} for {target_ts}"
                )
            if not 0.0 < coverage <= 1.0:
                raise StorageError(
                    f"coverage is the measured share of the hour in (0, 1]; got {coverage}"
                )
            payload.append((turbine_id, target_ts, actual_power, coverage))
        if not payload:
            raise StorageError("No actuals given")
        self.connection.executemany(
            "INSERT OR REPLACE INTO actuals VALUES (?, ?, ?, ?)", payload
        )
        return len(payload)

    # -- reading ---------------------------------------------------------

    def latest(self, turbine_id: int | None = None):
        """The forecast that currently stands for each hour."""
        if turbine_id is None:
            return self.connection.sql(
                "SELECT * FROM latest_forecasts ORDER BY turbine_id, target_ts"
            ).df()
        _check_turbine(turbine_id)
        return self.connection.execute(
            "SELECT * FROM latest_forecasts WHERE turbine_id = ? ORDER BY target_ts",
            [turbine_id],
        ).df()

    def revisions(self, turbine_id: int, target_ts: datetime):
        """Every forecast ever issued for one hour, oldest first."""
        _check_turbine(turbine_id)
        return self.connection.execute(
            """
            SELECT * FROM forecast_revisions
            WHERE turbine_id = ? AND target_ts = ?
            ORDER BY issued_at
            """,
            [turbine_id, target_ts],
        ).df()

    def accuracy_by_lead(self):
        """MAE and RMSE grouped by forecast lead, over hours that have a measurement."""
        return self.connection.sql(
            """
            SELECT
                turbine_id,
                lead_hours,
                count(*)                        AS hours,
                avg(abs(error))                 AS mae,
                sqrt(avg(error * error))        AS rmse,
                avg(error)                      AS bias
            FROM forecast_accuracy
            GROUP BY turbine_id, lead_hours
            ORDER BY turbine_id, lead_hours
            """
        ).df()

    def summary(self) -> dict[str, int]:
        """Row counts, for a quick health check."""
        tables = ("forecast_runs", "forecasts", "actuals")
        return {
            table: int(self.connection.sql(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in tables
        }

    # -- lifecycle -------------------------------------------------------

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ForecastStore":
        return self

    def __exit__(self, *exception) -> None:
        self.close()


def _check_turbine(turbine_id: int) -> None:
    if turbine_id not in TURBINES:
        raise StorageError(f"turbine_id must be one of {TURBINES}, got {turbine_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "summary", "accuracy"))
    parser.add_argument("--database", type=Path, default=DEFAULT_PATH)
    arguments = parser.parse_args()

    # Only "init" may create the file; the read commands must fail loudly
    # instead of silently handing back an empty database.
    try:
        with ForecastStore(arguments.database, read_only=arguments.command != "init") as store:
            if arguments.command == "init":
                print(f"Schema ready in {store.path}")
            elif arguments.command == "summary":
                for table, count in store.summary().items():
                    print(f"{table}: {count}")
            else:
                frame = store.accuracy_by_lead()
                print(frame.to_string(index=False) if len(frame) else "No measured hours yet")
    except StorageError as error:
        raise SystemExit(f"Error: {error}")


if __name__ == "__main__":
    main()
