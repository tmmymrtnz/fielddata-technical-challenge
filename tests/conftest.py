from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import joinedload
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.modules.alerts.models import Alert, AlertMetric, AlertOperator, AlertTrigger
from app.modules.alerts.service import build_delivery_row, build_trigger_snapshot
from app.modules.fields.models import Field
from app.modules.notifications.models import DeliveryStatus, NotificationDelivery
from app.modules.users.models import User
from app.modules.weather.models import WeatherForecast

HEAD_REVISION = "20260320_0003"
TEST_DATABASE_NAME = "climate_alerts_test"
TEST_ENV_FILE = Path(".env.test")
TRUNCATE_TABLES = ", ".join(table.name for table in reversed(Base.metadata.sorted_tables))


def _load_test_env_file() -> dict[str, str]:
    if not TEST_ENV_FILE.exists():
        return {}

    values = dotenv_values(TEST_ENV_FILE)
    return {key: value for key, value in values.items() if key is not None and value is not None}


def _database_url_from_sources() -> tuple[str | None, str | None]:
    for env_name in ("TEST_DATABASE_URL", "DATABASE_URL"):
        value = os.getenv(env_name)
        if value:
            return value, f"environment variable {env_name}"

    file_values = _load_test_env_file()
    for env_name in ("TEST_DATABASE_URL", "DATABASE_URL"):
        value = file_values.get(env_name)
        if value:
            return value, f"{TEST_ENV_FILE}:{env_name}"

    return None, None


def _require_database_url() -> URL:
    database_url, source = _database_url_from_sources()
    if not database_url:
        raise RuntimeError(
            "Postgres test suite requires TEST_DATABASE_URL. "
            "Set it in the environment or create .env.test from .env.test.example."
        )

    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError(f"Postgres test suite requires a PostgreSQL URL, got {url.drivername} from {source}")
    if url.database != TEST_DATABASE_NAME:
        raise RuntimeError(
            f"Postgres test suite requires a database named {TEST_DATABASE_NAME}, got {url.database} from {source}"
        )
    return url


def _admin_database_url(url: URL) -> str:
    return url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _test_db_connection_error(url: URL, exc: Exception) -> RuntimeError:
    host = url.host or "127.0.0.1"
    port = url.port or 5432
    user = url.username or "<missing-user>"
    error = RuntimeError(
        "Could not connect to the PostgreSQL test instance at "
        f"{host}:{port} as user {user!r}. "
        "If you are running tests locally, make sure Docker Compose is exposing the expected "
        "HOST_POSTGRES_PORT and that TEST_DATABASE_URL points to that same port."
    )
    error.__cause__ = exc
    return error


async def _recreate_database(url: URL) -> None:
    database_name = url.database
    assert database_name is not None

    try:
        connection = await asyncpg.connect(_admin_database_url(url))
    except (asyncpg.PostgresError, OSError) as exc:
        raise _test_db_connection_error(url, exc)
    try:
        quoted_database = _quote_identifier(database_name)
        await connection.execute(f"DROP DATABASE IF EXISTS {quoted_database} WITH (FORCE)")
        await connection.execute(f"CREATE DATABASE {quoted_database}")
    finally:
        await connection.close()


async def _drop_database(url: URL) -> None:
    database_name = url.database
    assert database_name is not None

    try:
        connection = await asyncpg.connect(_admin_database_url(url))
    except (asyncpg.PostgresError, OSError) as exc:
        raise _test_db_connection_error(url, exc)
    try:
        await connection.execute(f"DROP DATABASE IF EXISTS {_quote_identifier(database_name)} WITH (FORCE)")
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def postgres_test_database() -> str:
    get_settings.cache_clear()
    url = _require_database_url()
    asyncio.run(_recreate_database(url))

    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    command.upgrade(alembic_config, "head")

    yield url.render_as_string(hide_password=False)

    asyncio.run(_drop_database(url))


@pytest.fixture(scope="session")
def session_factory(postgres_test_database: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(postgres_test_database, future=True, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    asyncio.run(engine.dispose())


@pytest_asyncio.fixture(autouse=True)
async def reset_database(request: pytest.FixtureRequest) -> None:
    if {"tests", "unit"}.issubset(Path(str(request.fspath)).parts):
        return

    session_factory = request.getfixturevalue("session_factory")
    async with session_factory() as session:
        await session.execute(text(f"TRUNCATE TABLE {TRUNCATE_TABLES} RESTART IDENTITY CASCADE"))
        await session.commit()


@pytest_asyncio.fixture
async def db_session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncSession:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(session_factory: async_sessionmaker[AsyncSession]) -> AsyncClient:
    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


class FrozenTime:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def set(self, value: datetime) -> datetime:
        self.current = value
        return self.current

    def advance(self, **kwargs: Any) -> datetime:
        self.current += timedelta(**kwargs)
        return self.current

    def today(self) -> date:
        return self.current.date()


@pytest.fixture
def frozen_time(monkeypatch: pytest.MonkeyPatch) -> FrozenTime:
    clock = FrozenTime(datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc))
    monkeypatch.setattr("app.worker.jobs.utcnow", clock)
    monkeypatch.setattr("app.modules.alerts.service.utcnow", clock)
    return clock


class TestDataFactory:
    def __init__(self, session: AsyncSession, frozen_time: FrozenTime) -> None:
        self.session = session
        self.frozen_time = frozen_time
        self._user_index = 0
        self._field_index = 0
        self._alert_index = 0

    def _timestamps(self) -> dict[str, datetime]:
        now = self.frozen_time()
        return {"created_at": now, "updated_at": now}

    async def user(self, *, name: str | None = None, phone_number: str | None = None) -> User:
        self._user_index += 1
        user = User(
            name=name or f"User {self._user_index}",
            phone_number=phone_number or f"+549300000{self._user_index:04d}",
            **self._timestamps(),
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def field(self, *, user: User | None = None, user_id: int | None = None, name: str | None = None) -> Field:
        if user is None and user_id is None:
            user = await self.user()

        self._field_index += 1
        field = Field(
            user_id=user_id or user.id,
            name=name or f"Field {self._field_index}",
            **self._timestamps(),
        )
        self.session.add(field)
        await self.session.commit()
        await self.session.refresh(field)
        return field

    async def forecast(
        self,
        *,
        field: Field | None = None,
        field_id: int | None = None,
        forecast_date: date | None = None,
        source_updated_at: datetime | None = None,
        raw_payload: dict[str, Any] | None = None,
        **metric_values: int | None,
    ) -> WeatherForecast:
        if field is None and field_id is None:
            field = await self.field()

        defaults: dict[str, int | None] = {
            "temp_min_c": -1,
            "temp_max_c": 18,
            "rain_mm": 0,
            "rain_probability_pct": 5,
            "snow_mm": 0,
            "snow_probability_pct": 0,
            "wind_speed_mps": 6,
            "wind_gust_mps": 10,
        }
        defaults.update(metric_values)

        forecast = WeatherForecast(
            field_id=field_id or field.id,
            forecast_date=forecast_date or self.frozen_time.today(),
            source_updated_at=source_updated_at or self.frozen_time(),
            raw_payload=raw_payload or {"factory": True},
            **defaults,
            **self._timestamps(),
        )
        self.session.add(forecast)
        await self.session.commit()
        await self.session.refresh(forecast)
        return forecast

    async def alert(
        self,
        *,
        field: Field | None = None,
        field_id: int | None = None,
        name: str | None = None,
        metric: AlertMetric = AlertMetric.TEMP_MIN_C,
        operator: AlertOperator = AlertOperator.LTE,
        threshold_value: int = 0,
        lookahead_days: int = 1,
        is_active: bool = True,
        last_evaluated_at: datetime | None = None,
        deleted_at: datetime | None = None,
    ) -> Alert:
        if field is None and field_id is None:
            field = await self.field()

        self._alert_index += 1
        alert = Alert(
            field_id=field_id or field.id,
            name=name or f"Alert {self._alert_index}",
            metric=metric,
            operator=operator,
            threshold_value=threshold_value,
            lookahead_days=lookahead_days,
            is_active=is_active,
            last_evaluated_at=last_evaluated_at,
            deleted_at=deleted_at,
            **self._timestamps(),
        )
        self.session.add(alert)
        await self.session.commit()
        await self.session.refresh(alert)
        return alert

    async def trigger(
        self,
        *,
        alert: Alert | None = None,
        alert_id: int | None = None,
        forecast: WeatherForecast | None = None,
        forecast_id: int | None = None,
        triggered_value: int | None = None,
    ) -> AlertTrigger:
        resolved_alert_id = alert_id or (alert.id if alert is not None else None)
        resolved_forecast_id = forecast_id or (forecast.id if forecast is not None else None)
        if resolved_alert_id is None or resolved_forecast_id is None:
            raise ValueError("trigger requires an alert and a forecast")

        alert_result = await self.session.execute(
            select(Alert)
            .options(joinedload(Alert.field).joinedload(Field.user))
            .where(Alert.id == resolved_alert_id)
        )
        loaded_alert = alert_result.scalar_one()
        loaded_forecast = await self.session.get(WeatherForecast, resolved_forecast_id)
        assert loaded_forecast is not None

        value = triggered_value
        if value is None:
            value = getattr(loaded_forecast, loaded_alert.metric.value)
        assert value is not None

        trigger = AlertTrigger(**build_trigger_snapshot(loaded_alert, loaded_forecast, value))
        self.session.add(trigger)
        await self.session.commit()
        await self.session.refresh(trigger)
        return trigger

    async def delivery(
        self,
        *,
        trigger: AlertTrigger | None = None,
        trigger_id: int | None = None,
        target_url: str = "http://mock-whatsapp.test/webhook/whatsapp",
        status: DeliveryStatus = DeliveryStatus.PENDING,
        attempt_count: int = 0,
        next_attempt_at: datetime | None = None,
        last_error: str | None = None,
        response_status: int | None = None,
        sent_at: datetime | None = None,
    ) -> NotificationDelivery:
        resolved_trigger_id = trigger_id or (trigger.id if trigger is not None else None)
        if resolved_trigger_id is None:
            raise ValueError("delivery requires a trigger")

        row = build_delivery_row(resolved_trigger_id, target_url, next_attempt_at or self.frozen_time())
        row.update(
            {
                "status": status,
                "attempt_count": attempt_count,
                "last_error": last_error,
                "response_status": response_status,
                "sent_at": sent_at,
                "updated_at": self.frozen_time(),
            }
        )
        delivery = NotificationDelivery(**row)
        self.session.add(delivery)
        await self.session.commit()
        await self.session.refresh(delivery)
        return delivery


@pytest.fixture
def settings_factory() -> Any:
    database_url = _require_database_url().render_as_string(hide_password=False)

    def build(**overrides: Any) -> Settings:
        values = {
            "database_url": database_url,
            "mock_whatsapp_url": "http://mock-whatsapp.test/webhook/whatsapp",
            "worker_interval_minutes": 1,
            "worker_delivery_batch_size": 200,
            "delivery_max_retries": 3,
            "delivery_backoff_minutes": "1,5,15",
            "request_timeout_seconds": 10,
        }
        values.update(overrides)
        return Settings(**values)

    return build


@pytest.fixture
def factory(db_session: AsyncSession, frozen_time: FrozenTime) -> TestDataFactory:
    return TestDataFactory(db_session, frozen_time)
