COMPOSE=docker compose

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
	$(COMPOSE) run --rm api pytest

logs:
	$(COMPOSE) logs -f api worker mock-whatsapp db

