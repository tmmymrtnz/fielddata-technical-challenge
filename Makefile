COMPOSE=docker compose
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/climate_alerts_test

.PHONY: up infra app down migrate seed worker-once test logs

up:
	$(COMPOSE) up --build -d db mock-whatsapp
	$(COMPOSE) run --rm api alembic upgrade head
	$(COMPOSE) run --rm api python -m app.cli seed-demo --reset
	$(COMPOSE) up --build -d api worker

infra:
	$(COMPOSE) up --build -d db mock-whatsapp

app:
	$(COMPOSE) up --build -d api worker

down:
	$(COMPOSE) down --remove-orphans

migrate:
	$(COMPOSE) run --rm api alembic upgrade head

seed:
	$(COMPOSE) run --rm api python -m app.cli seed-demo --reset

worker-once:
	$(COMPOSE) run --rm worker python -m app.worker.main --run-once

test:
	$(COMPOSE) up --build -d db
	$(COMPOSE) run --rm --build -e DATABASE_URL=$(TEST_DATABASE_URL) api pytest

logs:
	$(COMPOSE) logs -f api worker mock-whatsapp db
