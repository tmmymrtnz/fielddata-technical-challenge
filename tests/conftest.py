from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.modules.users.models import User
from app.modules.fields.models import Field
from app.modules.weather.models import WeatherForecast
from app.db.base import utcnow
from datetime import date


@pytest.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_path = tmp_path / "test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        future=True,
        poolclass=NullPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
async def client(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
async def seeded_entities(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with session_factory() as session:
        user = User(name="Test User", phone_number="+5493000000000")
        session.add(user)
        await session.flush()

        field = Field(user_id=user.id, name="Campo Test")
        session.add(field)
        await session.flush()

        session.add(
            WeatherForecast(
                field_id=field.id,
                forecast_date=date.today(),
                source_updated_at=utcnow(),
                temp_min_c=-1,
                temp_max_c=18,
                rain_mm=20,
                rain_probability_pct=75,
                snow_mm=0,
                snow_probability_pct=0,
                wind_speed_mps=8,
                wind_gust_mps=14,
                raw_payload={"seeded_for_test": True},
            )
        )
        await session.commit()

        return {"user_id": user.id, "field_id": field.id}
