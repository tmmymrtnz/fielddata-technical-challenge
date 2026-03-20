from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.alerts.models import Alert, AlertMetric, AlertOperator
from app.modules.notifications.models import DeliveryStatus, NotificationDelivery
from app.modules.weather.models import WeatherForecast

HEAD_REVISION = "20260320_0003"


@pytest.mark.migration
async def test_database_is_migrated_to_head_with_scaling_index(session_factory) -> None:
    async with session_factory() as session:
        revision = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
        indexes = (
            await session.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public' AND tablename = 'alerts'
                    ORDER BY indexname
                    """
                )
            )
        ).scalars().all()

    assert revision == HEAD_REVISION
    assert indexes.count("ix_alerts_active_deleted_last_evaluated_id") == 1


async def test_weather_forecast_unique_constraint_on_field_and_date(factory, db_session) -> None:
    field = await factory.field()
    await factory.forecast(field=field)

    duplicate = WeatherForecast(
        field_id=field.id,
        forecast_date=factory.frozen_time.today(),
        source_updated_at=factory.frozen_time(),
        temp_min_c=-1,
        temp_max_c=18,
        rain_mm=0,
        rain_probability_pct=5,
        snow_mm=0,
        snow_probability_pct=0,
        wind_speed_mps=6,
        wind_gust_mps=10,
        raw_payload={"duplicate": True},
        created_at=factory.frozen_time(),
        updated_at=factory.frozen_time(),
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError, match="uq_weather_forecasts_field_id_forecast_date"):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.parametrize(
    ("override", "expected_constraint"),
    [
        ({"rain_probability_pct": 101}, "rain_probability_pct_bounds"),
        ({"snow_probability_pct": -1}, "snow_probability_pct_bounds"),
        ({"rain_mm": -1}, "rain_mm_non_negative"),
        ({"snow_mm": -1}, "snow_mm_non_negative"),
        ({"wind_speed_mps": -1}, "wind_speed_mps_non_negative"),
        ({"wind_gust_mps": -1}, "wind_gust_mps_non_negative"),
        ({"temp_min_c": 5, "temp_max_c": 4}, "temp_min_le_temp_max"),
    ],
)
async def test_weather_constraints_are_enforced(factory, db_session, override: dict[str, int], expected_constraint: str) -> None:
    field = await factory.field()
    values = {
        "field_id": field.id,
        "forecast_date": factory.frozen_time.today(),
        "source_updated_at": factory.frozen_time(),
        "temp_min_c": -1,
        "temp_max_c": 18,
        "rain_mm": 0,
        "rain_probability_pct": 5,
        "snow_mm": 0,
        "snow_probability_pct": 0,
        "wind_speed_mps": 6,
        "wind_gust_mps": 10,
        "raw_payload": {"invalid": True},
        "created_at": factory.frozen_time(),
        "updated_at": factory.frozen_time(),
    }
    values.update(override)
    forecast = WeatherForecast(**values)
    db_session.add(forecast)

    with pytest.raises(IntegrityError, match=expected_constraint):
        await db_session.commit()

    await db_session.rollback()


async def test_alert_lookahead_days_constraint_is_enforced(factory, db_session) -> None:
    field = await factory.field()
    invalid_alert = Alert(
        field_id=field.id,
        name="Invalid lookahead",
        metric=AlertMetric.TEMP_MIN_C,
        operator=AlertOperator.LTE,
        threshold_value=0,
        lookahead_days=0,
        is_active=True,
        created_at=factory.frozen_time(),
        updated_at=factory.frozen_time(),
    )
    db_session.add(invalid_alert)

    with pytest.raises(IntegrityError, match="lookahead_days_bounds"):
        await db_session.commit()

    await db_session.rollback()


async def test_alert_trigger_unique_constraint_is_enforced(factory, db_session) -> None:
    field = await factory.field()
    forecast = await factory.forecast(field=field, temp_min_c=-3)
    alert = await factory.alert(field=field, threshold_value=0)
    await factory.trigger(alert=alert, forecast=forecast, triggered_value=-3)

    with pytest.raises(IntegrityError, match="uq_alert_triggers_alert_id_weather_forecast_id"):
        await factory.trigger(alert=alert, forecast=forecast, triggered_value=-3)

    await db_session.rollback()


async def test_notification_delivery_attempt_count_constraint_is_enforced(factory, db_session) -> None:
    field = await factory.field()
    forecast = await factory.forecast(field=field, temp_min_c=-3)
    alert = await factory.alert(field=field, threshold_value=0)
    trigger = await factory.trigger(alert=alert, forecast=forecast, triggered_value=-3)
    invalid_delivery = NotificationDelivery(
        trigger_id=trigger.id,
        target_url="http://mock-whatsapp.test/webhook/whatsapp",
        status=DeliveryStatus.PENDING,
        attempt_count=-1,
        next_attempt_at=factory.frozen_time(),
        last_error=None,
        response_status=None,
        sent_at=None,
        created_at=factory.frozen_time(),
        updated_at=factory.frozen_time(),
    )
    db_session.add(invalid_delivery)

    with pytest.raises(IntegrityError, match="attempt_count_non_negative"):
        await db_session.commit()

    await db_session.rollback()
