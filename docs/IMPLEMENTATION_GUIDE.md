# Implementation Guide

This document captures the intended implementation shape of the challenge so the project can be built or extended without redesigning it from scratch.

## Goal

Implement a backend service that lets users define weather alerts on their fields, periodically evaluate stored daily forecasts, and produce idempotent notification triggers with retriable delivery to a mock webhook.

## Scope

- Daily weather forecasts already exist in the database through seed data or an external ingestion job.
- Alerts are configured per field.
- Each alert watches one metric with one operator and one threshold.
- Worker evaluation is periodic and asynchronous.
- Trigger creation must be idempotent.
- Delivery is mocked through an HTTP webhook.
- No authentication. All API reads and writes are scoped by `user_id`.

## Technical Stack

- FastAPI for HTTP APIs
- SQLAlchemy async ORM for data access
- PostgreSQL for production-like storage
- Alembic for versioned migrations
- HTTPX for webhook delivery
- Pytest for tests
- Docker Compose for reproducibility

## Architecture

- `app/main.py`: API entrypoint
- `app/worker/main.py`: worker entrypoint
- `app/mock_whatsapp/app.py`: mock downstream service
- `app/cli.py`: seed command

The worker is intentionally separated from the API process. That isolates batch execution from HTTP latency and keeps the scheduling logic out of the web app lifecycle.
The current implementation assumes a single worker instance. Horizontal worker scaling is out of scope for this version.

## Modeling Decisions

### Forecasts

- Granularity is daily.
- `weather_forecasts` has one row per `field_id + forecast_date`.
- Forecast values are stored in normalized columns, not provider-specific nested structures.

### Alerts

- Alerts are generic rules, not hardcoded event types.
- Metrics supported in v1:
  - `temp_min_c`
  - `temp_max_c`
  - `rain_mm`
  - `rain_probability_pct`
  - `snow_mm`
  - `snow_probability_pct`
  - `wind_speed_mps`
  - `wind_gust_mps`
- Operators supported in v1:
  - `lt`
  - `lte`
  - `gt`
  - `gte`
- `lookahead_days` is a per-alert integer bounded to `1..30`.

### Alert Semantics

- The worker evaluates each `forecast_date` independently.
- `lookahead_days` means "evaluate today plus the next `lookahead_days - 1` daily forecasts".
- `NULL` metrics do not trigger.
- Forecast updates can create new triggers on future worker cycles.
- Existing triggers are never canceled retroactively.
- Editing an alert affects future evaluations only.

### Trigger and Delivery Split

- `alert_triggers` stores the business event "this alert fired for this forecast".
- `notification_deliveries` stores delivery attempts and retry state.
- The split keeps idempotent trigger creation separate from operational delivery concerns.

## Worker Cycle

Each worker cycle does two things:

1. Evaluate active alerts against forecasts in their lookahead horizon.
2. Deliver pending or retryable notifications to the mock webhook.

Why all active alerts are reevaluated every cycle:

- daily windows move as time passes,
- edited alerts should take effect on the next cycle,
- updated forecasts should be picked up without additional orchestration,
- the challenge scale does not justify a more complex dirty-flag scheduler.

## Delivery Retries

- default max retries: `3`
- default backoff minutes: `1,5,15`
- `notification_deliveries.status` transitions:
  - `pending`
  - `retrying`
  - `delivered`
  - `failed`

## Reproducibility

Recommended demo flow:

1. `make up`
2. Open [http://localhost:8000/docs](http://localhost:8000/docs)
3. Create or edit an alert
4. Run `make worker-once` if you want an immediate demonstration
5. Check `GET /notifications?user_id=...`
6. Watch webhook logs with `make logs`

## Suggested Implementation Order

1. Base project scaffold and settings
2. SQLAlchemy models and Alembic migration
3. Seed CLI
4. Alert evaluator unit tests
5. Alerts API
6. Worker evaluation and idempotent trigger creation
7. Mock webhook and delivery retries
8. Notifications API
9. Docker Compose, Makefile, and README polish
