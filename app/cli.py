from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.session import SessionLocal
from app.modules.alerts.models import Alert, AlertMetric, AlertOperator, AlertTrigger
from app.modules.fields.models import Field
from app.modules.notifications.models import NotificationDelivery
from app.modules.users.models import User
from app.modules.weather.models import WeatherForecast


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Climate alerts project CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed-demo", help="Seed demo users, fields, forecasts, and sample alerts")
    seed_parser.add_argument("--reset", action="store_true", help="Reset existing data before seeding")
    return parser.parse_args()


async def reset_data(session: AsyncSession) -> None:
    dialect_name = session.bind.dialect.name
    if dialect_name == "postgresql":
        await session.execute(
            text(
                "TRUNCATE TABLE notification_deliveries, alert_triggers, alerts, "
                "weather_forecasts, fields, users RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
        return

    for model in (NotificationDelivery, AlertTrigger, Alert, WeatherForecast, Field, User):
        await session.execute(delete(model))
    if dialect_name == "sqlite":
        await session.execute(text("DELETE FROM sqlite_sequence"))
    await session.commit()


async def seed_demo(reset: bool) -> None:
    async with SessionLocal() as session:
        if reset:
            await reset_data(session)
        else:
            existing_user = await session.execute(select(User.id).limit(1))
            if existing_user.scalar_one_or_none() is not None:
                return

        users = [
            User(name="Alice Farmer", phone_number="+5491111111111"),
            User(name="Bob Grower", phone_number="+5492222222222"),
        ]
        session.add_all(users)
        await session.flush()

        fields = [
            Field(user_id=users[0].id, name="Campo Norte"),
            Field(user_id=users[0].id, name="Campo Sur"),
            Field(user_id=users[1].id, name="Lote Este"),
            Field(user_id=users[1].id, name="Lote Oeste"),
        ]
        session.add_all(fields)
        await session.flush()

        today = date.today()
        forecast_rows: list[WeatherForecast] = []
        for field_index, field in enumerate(fields, start=1):
            for offset in range(0, 10):
                forecast_rows.append(
                    WeatherForecast(
                        field_id=field.id,
                        forecast_date=today + timedelta(days=offset),
                        source_updated_at=utcnow(),
                        temp_min_c=-2 + offset + (field_index - 1),
                        temp_max_c=12 + offset + field_index,
                        rain_mm=0 if offset % 2 == 0 else 18 + field_index,
                        rain_probability_pct=15 if offset % 2 == 0 else 70,
                        snow_mm=2 if field_index == 3 and offset in (2, 3) else 0,
                        snow_probability_pct=65 if field_index == 3 and offset in (2, 3) else 5,
                        wind_speed_mps=6 + offset,
                        wind_gust_mps=10 + offset + field_index,
                        raw_payload={"seed": True, "field_index": field_index, "offset": offset},
                    )
                )
        session.add_all(forecast_rows)
        await session.flush()

        alerts = [
            Alert(
                field_id=fields[0].id,
                name="Helada Campo Norte",
                metric=AlertMetric.TEMP_MIN_C,
                operator=AlertOperator.LTE,
                threshold_value=0,
                lookahead_days=5,
                is_active=True,
            ),
            Alert(
                field_id=fields[1].id,
                name="Lluvia Campo Sur",
                metric=AlertMetric.RAIN_MM,
                operator=AlertOperator.GTE,
                threshold_value=18,
                lookahead_days=4,
                is_active=True,
            ),
            Alert(
                field_id=fields[2].id,
                name="Viento Lote Este",
                metric=AlertMetric.WIND_GUST_MPS,
                operator=AlertOperator.GTE,
                threshold_value=15,
                lookahead_days=7,
                is_active=True,
            ),
            Alert(
                field_id=fields[3].id,
                name="Lluvia Probable Lote Oeste",
                metric=AlertMetric.RAIN_PROBABILITY_PCT,
                operator=AlertOperator.GTE,
                threshold_value=60,
                lookahead_days=6,
                is_active=True,
            ),
        ]
        session.add_all(alerts)
        await session.commit()


def main() -> None:
    args = parse_args()
    if args.command == "seed-demo":
        asyncio.run(seed_demo(reset=args.reset))


if __name__ == "__main__":
    main()
