# Climate Alerts Challenge

Backend technical challenge for a climate alerting system built with FastAPI, SQLAlchemy, PostgreSQL, Alembic, and an async worker.

## What This Solves

The system allows users to configure weather alerts on their fields, periodically evaluates stored forecast data, and creates notifications when a configured threshold is met.

This repository includes:

- REST API endpoints
- background worker for alert evaluation
- PostgreSQL schema and Alembic migrations
- mock weather data seeding
- mock notification delivery over HTTP
- unit and integration tests

WhatsApp integration is intentionally not implemented. Instead, notifications are delivered to a mock webhook service that logs the received payload.

## Assumptions And Scope

I made these explicit assumptions to keep the implementation focused and production-oriented:

- Forecast granularity is daily.
- Weather data is already ingested and stored in the database.
- For the exercise, ingestion is mocked with a seed script.
- Alerts are modeled as generic rules over stored metrics rather than hardcoded event-specific logic.
- No authentication layer is included; API access is scoped by `user_id`.
- A field belongs to exactly one user.

## Main Design Decisions

### Modular Monolith With Two Processes

The project is implemented as a modular monolith with separate entrypoints for:

- `api`: serves HTTP traffic
- `worker`: periodically evaluates alerts and delivers notifications

Both share the same codebase and domain model, but run as separate processes. This keeps the API responsive and avoids coupling request latency to batch execution.

### Weather Data Model

Forecasts are stored in a single daily table: `weather_forecasts`.

Supported metrics in v1:

- `temp_min_c`
- `temp_max_c`
- `rain_mm`
- `rain_probability_pct`
- `snow_mm`
- `snow_probability_pct`
- `wind_speed_mps`
- `wind_gust_mps`

I intentionally removed `weather_code` for this version to avoid inventing event semantics not strictly required by the challenge.

### Alert Model

Alerts are defined by:

- `field_id`
- `metric`
- `operator`
- `threshold_value`
- `lookahead_days`

Operators supported:

- `lt`
- `lte`
- `gt`
- `gte`

`lookahead_days` is configured per alert and constrained to `1..30`.

### Business Rules

- Each forecast day is evaluated independently.
- A single alert can trigger once per `forecast_date`.
- `NULL` metric values do not trigger alerts.
- Alerts are soft deleted.
- Editing an alert affects future worker cycles only.
- Existing triggers are not canceled if forecast data changes later.

### Idempotency

Idempotency is enforced at the database level through:

- `UNIQUE(field_id, forecast_date)` on `weather_forecasts`
- `UNIQUE(alert_id, weather_forecast_id)` on `alert_triggers`

This guarantees that rerunning the worker does not generate duplicate triggers for the same alert and forecast row.

### Trigger Creation vs Delivery

I separated business triggering from outbound delivery:

- `alert_triggers`: the alert condition was met
- `notification_deliveries`: the system attempted to send the notification

This keeps the core alerting logic clean and allows retries without duplicating business events.

## Data Model

Main tables:

- `users`
- `fields`
- `weather_forecasts`
- `alerts`
- `alert_triggers`
- `notification_deliveries`

`alert_triggers` stores a snapshot of the alert rule at trigger time, so notification history remains stable even if the alert is edited later.

## Async And Background Processing

The worker is asynchronous and runs independently from the API.

Each cycle:

1. Loads active alerts.
2. Looks up forecasts for each alert horizon.
3. Evaluates the configured metric/operator/threshold.
4. Inserts missing triggers idempotently.
5. Creates pending delivery rows.
6. Sends pending notifications to the mock webhook.
7. Retries failed deliveries with backoff.

Default worker interval is `1` minute, configurable with `--interval-minutes`.

## How Weather Data Is Mocked

The challenge states that a weather ingestion job already exists. For this exercise, that ingestion is mocked through a seed command that inserts:

- `12` users by default
- `48` fields by default, with multiple fields per user
- `720` daily forecasts by default
- `144` sample alerts by default

The first seeded users and fields stay human-readable for demos:

- `Alice Farmer`: `Campo Norte`, `Campo Sur`, `Campo Central`, `Campo Oeste`
- `Bob Grower`: `Lote Este`, `Lote Oeste`, `Lote Norte`, `Lote Sur`

Seed command:

```bash
python -m app.cli seed-demo --reset
```

You can also scale the dataset up or down:

```bash
python -m app.cli seed-demo --reset --users 20 --fields-per-user 5 --forecast-days 21
```

## How To Run

The easiest way to reproduce the project is with Docker Compose.

### Prerequisites

- Docker
- Docker Compose

### Startup

```bash
make up
```

This will:

- start PostgreSQL
- start the mock notification webhook
- apply Alembic migrations
- seed demo data
- start the API
- start the worker

API docs:

- [http://localhost:8000/docs](http://localhost:8000/docs)

### Useful Commands

- `make migrate`
- `make seed`
- `make worker-once`
- `make test`
- `make logs`
- `make down`

## API Overview

- `GET /health`
- `GET /fields?user_id=1`
- `POST /alerts`
- `GET /alerts?user_id=1`
- `PATCH /alerts/{id}?user_id=1`
- `DELETE /alerts/{id}?user_id=1`
- `GET /notifications?user_id=1`

Example alert payload:

```json
{
  "user_id": 1,
  "field_id": 1,
  "name": "Helada campo norte",
  "metric": "temp_min_c",
  "operator": "lte",
  "threshold_value": 0,
  "lookahead_days": 5
}
```

## Migrations

Alembic is used for schema versioning.

Run migrations manually with:

```bash
make migrate
```

Initial migration lives in:

- `alembic/versions/20260320_0001_initial_schema.py`

## Tests

The repository includes:

- unit tests for the metric evaluator
- integration tests covering alert creation, worker execution, notification generation, and soft delete behavior

Run tests with:

```bash
make test
```

I also verified the implementation locally with `pytest` in a project virtualenv.

## Demo Notes

- Notification delivery is mocked through an HTTP webhook, not WhatsApp.
- The webhook logs the payload to stdout.
- Retry behavior can be demonstrated by setting `MOCK_WHATSAPP_FAIL_FIRST_DELIVERY=true`.

## Repository Structure

- `app/`: application code
- `alembic/`: migrations
- `tests/`: unit and integration tests
- `docs/`: implementation notes

## Possible Next Steps

If this were extended beyond the challenge, the next improvements I would consider are:

- real authentication and authorization
- stronger observability around worker cycles
- pagination/filtering on notifications
- explicit locking strategy if running multiple worker instances
- real ingestion integration instead of seeded forecasts
