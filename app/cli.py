from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
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


DEFAULT_USER_COUNT = 12
DEFAULT_FIELDS_PER_USER = 4
DEFAULT_FORECAST_DAYS = 15


@dataclass(frozen=True)
class AlertTemplate:
    label: str
    metric: AlertMetric
    operator: AlertOperator
    threshold_value: int
    lookahead_days: int


BASE_USER_BLUEPRINTS = [
    (
        "Alice Farmer",
        "+5491111111111",
        ["Campo Norte", "Campo Sur", "Campo Central", "Campo Oeste"],
    ),
    (
        "Bob Grower",
        "+5492222222222",
        ["Lote Este", "Lote Oeste", "Lote Norte", "Lote Sur"],
    ),
]

ALERT_TEMPLATES = [
    AlertTemplate("Helada", AlertMetric.TEMP_MIN_C, AlertOperator.LTE, 0, 5),
    AlertTemplate("Lluvia", AlertMetric.RAIN_MM, AlertOperator.GTE, 18, 4),
    AlertTemplate("Rafagas", AlertMetric.WIND_GUST_MPS, AlertOperator.GTE, 16, 7),
    AlertTemplate("Calor", AlertMetric.TEMP_MAX_C, AlertOperator.GTE, 30, 4),
    AlertTemplate("Prob Lluvia", AlertMetric.RAIN_PROBABILITY_PCT, AlertOperator.GTE, 60, 6),
    AlertTemplate("Nieve", AlertMetric.SNOW_MM, AlertOperator.GTE, 2, 5),
    AlertTemplate("Prob Nieve", AlertMetric.SNOW_PROBABILITY_PCT, AlertOperator.GTE, 55, 5),
    AlertTemplate("Viento", AlertMetric.WIND_SPEED_MPS, AlertOperator.GTE, 12, 6),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Climate alerts project CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed-demo", help="Seed demo users, fields, forecasts, and sample alerts")
    seed_parser.add_argument("--reset", action="store_true", help="Reset existing data before seeding")
    seed_parser.add_argument(
        "--users",
        type=int,
        default=DEFAULT_USER_COUNT,
        help=f"Number of users to create (default: {DEFAULT_USER_COUNT})",
    )
    seed_parser.add_argument(
        "--fields-per-user",
        type=int,
        default=DEFAULT_FIELDS_PER_USER,
        help=f"Fields to create per user (default: {DEFAULT_FIELDS_PER_USER})",
    )
    seed_parser.add_argument(
        "--forecast-days",
        type=int,
        default=DEFAULT_FORECAST_DAYS,
        help=f"Daily forecasts to create per field (default: {DEFAULT_FORECAST_DAYS})",
    )
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


def _generated_phone_number(user_number: int) -> str:
    return f"+54930{user_number:08d}"


def _field_name_for(user_number: int, field_number: int, fields_per_user: int) -> str:
    if user_number <= len(BASE_USER_BLUEPRINTS):
        blueprint_fields = BASE_USER_BLUEPRINTS[user_number - 1][2]
        if field_number <= len(blueprint_fields):
            return blueprint_fields[field_number - 1]
        return f"Sector {field_number:02d}"

    return f"Predio {user_number:02d}-{field_number:02d}"


def _build_users(user_count: int) -> list[User]:
    users: list[User] = []
    for user_number in range(1, user_count + 1):
        if user_number <= len(BASE_USER_BLUEPRINTS):
            name, phone_number, _ = BASE_USER_BLUEPRINTS[user_number - 1]
        else:
            name = f"Demo Grower {user_number:02d}"
            phone_number = _generated_phone_number(user_number)
        users.append(User(name=name, phone_number=phone_number))
    return users


def _forecast_values(field_index: int, offset: int) -> dict[str, int | None]:
    cold_shift = (field_index % 6) - 3
    temp_min_c = -5 + cold_shift + offset // 4
    temp_max_c = temp_min_c + 11 + ((field_index + offset) % 6)

    rain_event = (field_index + offset) % 3 == 0
    rain_mm = 14 + (field_index % 8) + (offset % 5) if rain_event else 0
    rain_probability_pct = None if offset % 6 == 0 else 25 + ((field_index * 11 + offset * 7) % 70)

    snow_event = field_index % 7 in (0, 1) and offset in (1, 2, 5, 9, 12)
    snow_mm = 1 + ((field_index + offset) % 4) if snow_event else 0
    if offset % 5 == 0:
        snow_probability_pct = None
    elif snow_event:
        snow_probability_pct = 55 + ((field_index + offset) % 30)
    else:
        snow_probability_pct = 5 + ((field_index + offset) % 20)

    wind_speed_mps = 5 + ((field_index * 2 + offset) % 11)
    wind_gust_mps = wind_speed_mps + 4 + (field_index % 7)

    return {
        "temp_min_c": temp_min_c,
        "temp_max_c": temp_max_c,
        "rain_mm": rain_mm,
        "rain_probability_pct": rain_probability_pct,
        "snow_mm": snow_mm,
        "snow_probability_pct": snow_probability_pct,
        "wind_speed_mps": wind_speed_mps,
        "wind_gust_mps": wind_gust_mps,
    }


def _threshold_for(template: AlertTemplate, field_index: int, template_offset: int) -> int:
    adjustment = (field_index + template_offset) % 3
    if template.metric in {
        AlertMetric.RAIN_PROBABILITY_PCT,
        AlertMetric.SNOW_PROBABILITY_PCT,
    }:
        return min(template.threshold_value + (adjustment * 5), 100)
    if template.metric in {AlertMetric.TEMP_MIN_C}:
        return template.threshold_value - adjustment
    return template.threshold_value + adjustment


async def seed_demo(
    reset: bool,
    user_count: int,
    fields_per_user: int,
    forecast_days: int,
) -> None:
    if user_count < 2:
        raise ValueError("seed-demo requires at least 2 users")
    if fields_per_user < 2:
        raise ValueError("seed-demo requires at least 2 fields per user")
    if forecast_days < 7:
        raise ValueError("seed-demo requires at least 7 forecast days")

    async with SessionLocal() as session:
        if reset:
            await reset_data(session)
        else:
            existing_user = await session.execute(select(User.id).limit(1))
            if existing_user.scalar_one_or_none() is not None:
                print("Seed skipped: database already contains users.")
                return

        users = _build_users(user_count)
        session.add_all(users)
        await session.flush()

        fields: list[Field] = []
        for user_number, user in enumerate(users, start=1):
            for field_number in range(1, fields_per_user + 1):
                fields.append(
                    Field(
                        user_id=user.id,
                        name=_field_name_for(user_number, field_number, fields_per_user),
                    )
                )
        session.add_all(fields)
        await session.flush()

        today = date.today()
        forecast_rows: list[WeatherForecast] = []
        for field_index, field in enumerate(fields, start=1):
            for offset in range(forecast_days):
                forecast_values = _forecast_values(field_index, offset)
                forecast_rows.append(
                    WeatherForecast(
                        field_id=field.id,
                        forecast_date=today + timedelta(days=offset),
                        source_updated_at=utcnow(),
                        temp_min_c=forecast_values["temp_min_c"],
                        temp_max_c=forecast_values["temp_max_c"],
                        rain_mm=forecast_values["rain_mm"],
                        rain_probability_pct=forecast_values["rain_probability_pct"],
                        snow_mm=forecast_values["snow_mm"],
                        snow_probability_pct=forecast_values["snow_probability_pct"],
                        wind_speed_mps=forecast_values["wind_speed_mps"],
                        wind_gust_mps=forecast_values["wind_gust_mps"],
                        raw_payload={
                            "seed": True,
                            "field_index": field_index,
                            "offset": offset,
                            "forecast_days": forecast_days,
                        },
                    )
                )
        session.add_all(forecast_rows)
        await session.flush()

        alerts: list[Alert] = []
        for field_index, field in enumerate(fields, start=1):
            for template_offset in range(3):
                template = ALERT_TEMPLATES[(field_index + template_offset - 1) % len(ALERT_TEMPLATES)]
                alerts.append(
                    Alert(
                        field_id=field.id,
                        name=f"{template.label} {field.name}",
                        metric=template.metric,
                        operator=template.operator,
                        threshold_value=_threshold_for(template, field_index, template_offset),
                        lookahead_days=min(template.lookahead_days + ((field_index + template_offset) % 3), 30),
                        is_active=True,
                    )
                )
        session.add_all(alerts)
        await session.commit()
        print(
            "Seed completed: "
            f"{len(users)} users, "
            f"{len(fields)} fields, "
            f"{len(forecast_rows)} forecasts, "
            f"{len(alerts)} alerts."
        )


def main() -> None:
    args = parse_args()
    if args.command == "seed-demo":
        asyncio.run(
            seed_demo(
                reset=args.reset,
                user_count=args.users,
                fields_per_user=args.fields_per_user,
                forecast_days=args.forecast_days,
            )
        )


if __name__ == "__main__":
    main()
