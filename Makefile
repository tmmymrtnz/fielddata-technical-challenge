COMPOSE=docker compose
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/climate_alerts_test
HOST_POSTGRES_PORT?=55432
LOCAL_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:$(HOST_POSTGRES_PORT)/climate_alerts_test
DEMO_SEED_ARGS=--reset --users 2 --fields-per-user 2 --forecast-days 10

.PHONY: up infra app demo down migrate seed worker-once test test-local logs

up:
	$(COMPOSE) up --build -d db mock-whatsapp
	$(COMPOSE) run --rm api alembic upgrade head
	$(COMPOSE) run --rm api python -m app.cli seed-demo --reset
	$(COMPOSE) up --build -d api worker

infra:
	$(COMPOSE) up --build -d db mock-whatsapp

app:
	$(COMPOSE) up --build -d api worker

demo:
	$(COMPOSE) down --remove-orphans
	$(COMPOSE) up --build -d --wait db mock-whatsapp
	$(COMPOSE) run --rm --build api alembic upgrade head
	$(COMPOSE) run --rm --build api python -m app.cli seed-demo $(DEMO_SEED_ARGS)
	$(COMPOSE) up --build -d api

down:
	$(COMPOSE) down --remove-orphans

migrate:
	$(COMPOSE) run --rm api alembic upgrade head

seed:
	$(COMPOSE) run --rm api python -m app.cli seed-demo --reset

worker-once:
	$(COMPOSE) run --rm worker python -m app.worker.main --run-once

test:
	HOST_POSTGRES_PORT=$(HOST_POSTGRES_PORT) $(COMPOSE) up --build -d --wait db
	$(COMPOSE) run --rm --build -e TEST_DATABASE_URL=$(TEST_DATABASE_URL) api pytest

test-local:
	HOST_POSTGRES_PORT=$(HOST_POSTGRES_PORT) $(COMPOSE) up -d --wait db
	TEST_DATABASE_URL=$${TEST_DATABASE_URL:-$(LOCAL_TEST_DATABASE_URL)} ./.venv/bin/python -m pytest

logs:
	$(COMPOSE) logs -f api worker mock-whatsapp db
