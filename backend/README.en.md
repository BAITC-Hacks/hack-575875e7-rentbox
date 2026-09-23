# Wind Farm Dashboard Backend

[Русский](README.md) · **English** · [Қазақша](README.kk.md)

Python 3.12, FastAPI, Pydantic, DuckDB. Single entry point from the repository root:
`src.api:app`. Public contract: [docs/API.md](../docs/API.md); machine-readable
specification: [openapi.json](openapi.json).

## Our Area of Work

The dashboard backend owns the HTTP API, the job queue, states, events,
result delivery, CSV and sequential replay. The agent developer
implements weather, feature preparation, the model and decision-making.
Integration interface: [agent-integration.md](../docs/backend/agent-integration.md).

Our colleague's original store `src/storage.py` is used through `ForecastStore`.
Its tables and methods are unchanged. In the same DuckDB file, additional
tables `api_runs` and `api_replays` are created: HTTP identifiers, states,
provenance metadata, revision links and full API responses.

## Structure

```text
src/api.py                        # Shared ASGI entry point
src/storage.py                    # Colleague's forecast store
backend/
├── app/
│   ├── main.py                   # Application assembly, lifespan, CORS
│   ├── api/
│   │   ├── deps.py
│   │   ├── router.py             # /api
│   │   └── routes/               # health, turbines, data, agent
│   ├── core/                     # Settings and unified error format
│   ├── schemas/                  # Requests, responses, agent result
│   ├── services/
│   │   ├── turbines.py           # Real catalog of the two turbines
│   │   ├── data.py               # Audit summary and CSV SHA-256 verification
│   │   └── forecasts.py          # Queue, replay, CSV
│   └── integrations/
│       ├── forecasting.py        # ForecastEngine and AgentContext
│       └── storage.py            # States and the ForecastStore adapter
├── config/turbines.json
├── scripts/export_openapi.py
├── tests/
├── openapi.json
├── pyproject.toml
├── uv.lock
└── Dockerfile
```

## Running

From the root: `make dev` or `docker compose up --build`.
Full installation and environment variables are in the [README](../README.md).

API: `http://localhost:8000/api`; Swagger: `http://localhost:8000/docs`.
The origins `http://localhost:5173` and `http://localhost:3000` are allowed for the frontend;
others are set via the JSON array `RENTBOX_CORS_ORIGINS`.

**One Uvicorn process and one agent worker thread** are used.
HTTP requests do not wait for the model to finish. Short DuckDB operations are protected
by a shared lock; the agent call runs outside it. Do not start another API or CLI
that opens the same DuckDB file while the server is running.
Concurrent writes from multiple processes would require a different architecture.

## Job Behavior

- POST returns 202, a string ID and a Location header once the job is written.
- Accepted jobs and all events are stored in DuckDB.
- The full result for both turbines, the numeric storage_run_id values and the final status
  are written in a single transaction.
- The following are validated: the set of turbines, 24/48 ordered hours, power 0–1,
  the weather provenance of each hour/model and availability as of `as_of`.
  For Previous Runs the estimate is recomputed as `valid_time - offset * 24h + 12h`;
  unknown issue/publication dates remain `null`. The estimation policy is explicitly
  flagged with a warning. Training targets must be available as of `as_of`.
- Dates are accepted with a time zone and normalized to UTC. For the current ForecastStore
  tzinfo is stripped before writing; JSON returns Z.
- With an unchanged input_sha256 the result is reused with reused_run_id.
  Numbers, model and provenance must match for an identical hash;
  re-download time, source order and local source_id values are ignored.
  Changed inputs create a new revision and supersedes_run_id.
- A repeated POST creates a separate input-validation job. This is not HTTP
  idempotency by request key.
- Replay creates all child IDs, then executes them sequentially in 24-hour steps.
  A failure of an individual run does not cancel the following ones. The final status
  is failed if at least one child run ended with an error.
- Replay bounds are inclusive. The horizon is kept in full, even beyond February.
- After a restart, queued/running move to failed/JOB_INTERRUPTED;
  completed results remain available. There is no automatic resumption.
- The queue is limited to 128 runs, a single replay to 62, and a run log to 500 events.
  The values are configurable via the environment.

Completeness and authenticity of the weather source, publication time and correctness
of training are the agent's responsibility. The backend validates the submitted metadata and format,
but does not itself establish the fact of historical availability of an issue.

Contract v0.3: `series.weather.sources` and `points[].weather_inputs`.
The CSV contains one row per forecast hour; metadata for multiple models is
in `weather_inputs_json`. Legacy responses with a single weather issue are converted
on read. [Details for the agent and frontend](../docs/backend/weather-provenance.md).

## Without a Connected Agent

The catalog, health, data summary, Swagger and reading of previously stored results
are available. While the time is unconfirmed, POST responds with
409 CONFIGURATION_REQUIRED. After the time is configured but without an agent module —
503 AGENT_NOT_CONFIGURED. No artificial successful forecasts are produced.

## Developer Commands

```bash
make openapi
make lint
make test
```

OpenAPI is generated without opening the database and without executing the agent.
The existing tests have been adapted to the /api contract; they were not run
during this implementation. The OpenAPI export and static analysis have been performed.
The Docker build and the full scenario with a real agent have not been verified yet.

## Library Documentation

- [FastAPI: structure](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
  and [lifespan](https://fastapi.tiangolo.com/advanced/events/).
- [Pydantic: validation](https://docs.pydantic.dev/latest/concepts/validators/).
- [DuckDB: Python DB API](https://duckdb.org/docs/current/clients/python/dbapi)
  and [concurrent access](https://duckdb.org/docs/current/connect/concurrency).
