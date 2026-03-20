from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.alerts.models import Alert, AlertMetric, AlertOperator, AlertTrigger
from app.modules.notifications.models import DeliveryStatus, NotificationDelivery
from app.modules.weather.models import WeatherForecast

HEAD_REVISION = "20260320_0005"


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
    assert indexes.count("uq_alerts_active_rule") == 1


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


async def test_deleted_alerts_cannot_remain_active(factory, db_session) -> None:
    field = await factory.field()
    invalid_alert = Alert(
        field_id=field.id,
        name="Deleted but active",
        metric=AlertMetric.TEMP_MIN_C,
        operator=AlertOperator.LTE,
        threshold_value=0,
        lookahead_days=2,
        is_active=True,
        deleted_at=factory.frozen_time(),
        created_at=factory.frozen_time(),
        updated_at=factory.frozen_time(),
    )
    db_session.add(invalid_alert)

    with pytest.raises(IntegrityError, match="deleted_alerts_must_be_inactive"):
        await db_session.commit()

    await db_session.rollback()


async def test_duplicate_active_alert_rules_are_rejected(factory, db_session) -> None:
    field = await factory.field()
    await factory.alert(
        field=field,
        metric=AlertMetric.TEMP_MIN_C,
        operator=AlertOperator.LTE,
        threshold_value=0,
        lookahead_days=2,
    )
    duplicate_alert = Alert(
        field_id=field.id,
        name="Duplicate active rule",
        metric=AlertMetric.TEMP_MIN_C,
        operator=AlertOperator.LTE,
        threshold_value=0,
        lookahead_days=2,
        is_active=True,
        created_at=factory.frozen_time(),
        updated_at=factory.frozen_time(),
    )
    db_session.add(duplicate_alert)

    with pytest.raises(IntegrityError, match="uq_alerts_active_rule"):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.parametrize(
    ("metric", "threshold_value", "expected_constraint"),
    [
        (AlertMetric.RAIN_PROBABILITY_PCT, 150, "threshold_probability_bounds"),
        (AlertMetric.RAIN_MM, -1, "threshold_non_negative_for_metric"),
    ],
)
async def test_alert_threshold_constraints_are_enforced(
    factory,
    db_session,
    metric: AlertMetric,
    threshold_value: int,
    expected_constraint: str,
) -> None:
    field = await factory.field()
    invalid_alert = Alert(
        field_id=field.id,
        name="Invalid threshold",
        metric=metric,
        operator=AlertOperator.GTE,
        threshold_value=threshold_value,
        lookahead_days=2,
        is_active=True,
        created_at=factory.frozen_time(),
        updated_at=factory.frozen_time(),
    )
    db_session.add(invalid_alert)

    with pytest.raises(IntegrityError, match=expected_constraint):
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


async def test_alert_trigger_snapshot_threshold_constraints_are_enforced(factory, db_session) -> None:
    field = await factory.field()
    forecast = await factory.forecast(field=field, rain_probability_pct=80)
    alert = await factory.alert(
        field=field,
        metric=AlertMetric.RAIN_PROBABILITY_PCT,
        operator=AlertOperator.GTE,
        threshold_value=70,
        lookahead_days=2,
    )
    invalid_trigger = AlertTrigger(
        alert_id=alert.id,
        weather_forecast_id=forecast.id,
        user_id_snapshot=field.user_id,
        phone_number_snapshot="+5493000000001",
        field_id_snapshot=field.id,
        field_name_snapshot=field.name,
        forecast_date_snapshot=forecast.forecast_date,
        alert_name_snapshot="Invalid trigger snapshot",
        metric_snapshot=AlertMetric.RAIN_PROBABILITY_PCT,
        operator_snapshot=AlertOperator.GTE,
        threshold_value_snapshot=150,
        lookahead_days_snapshot=2,
        triggered_value=80,
        message="Invalid trigger snapshot",
        created_at=factory.frozen_time(),
        updated_at=factory.frozen_time(),
    )
    db_session.add(invalid_trigger)

    with pytest.raises(IntegrityError, match="threshold_probability_snapshot_bounds"):
        await db_session.commit()

    await db_session.rollback()


async def test_alert_trigger_snapshot_lookahead_bounds_are_enforced(factory, db_session) -> None:
    field = await factory.field()
    forecast = await factory.forecast(field=field, temp_min_c=-3)
    alert = await factory.alert(
        field=field,
        metric=AlertMetric.TEMP_MIN_C,
        operator=AlertOperator.LTE,
        threshold_value=0,
        lookahead_days=2,
    )
    invalid_trigger = AlertTrigger(
        alert_id=alert.id,
        weather_forecast_id=forecast.id,
        user_id_snapshot=field.user_id,
        phone_number_snapshot="+5493000000001",
        field_id_snapshot=field.id,
        field_name_snapshot=field.name,
        forecast_date_snapshot=forecast.forecast_date,
        alert_name_snapshot="Invalid snapshot lookahead",
        metric_snapshot=AlertMetric.TEMP_MIN_C,
        operator_snapshot=AlertOperator.LTE,
        threshold_value_snapshot=0,
        lookahead_days_snapshot=0,
        triggered_value=-3,
        message="Invalid snapshot lookahead",
        created_at=factory.frozen_time(),
        updated_at=factory.frozen_time(),
    )
    db_session.add(invalid_trigger)

    with pytest.raises(IntegrityError, match="lookahead_days_snapshot_bounds"):
        await db_session.commit()

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

    with pytest.raises(IntegrityError, match="attempt_count_(non_negative|matches_status)"):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.parametrize(
    ("override", "expected_constraint"),
    [
        (
            {
                "status": DeliveryStatus.DELIVERED,
                "attempt_count": 1,
                "response_status": 202,
                "last_error": None,
                "sent_at": None,
            },
            "sent_at_matches_status",
        ),
        (
            {
                "status": DeliveryStatus.DELIVERED,
                "attempt_count": 1,
                "response_status": 500,
                "last_error": None,
                "sent_at": None,
            },
            "delivered_response_status_bounds",
        ),
        (
            {
                "status": DeliveryStatus.DELIVERED,
                "attempt_count": 1,
                "response_status": 202,
                "last_error": "should be empty",
                "sent_at": None,
            },
            "delivered_last_error_cleared",
        ),
        (
            {
                "status": DeliveryStatus.PENDING,
                "attempt_count": 1,
                "response_status": None,
                "last_error": None,
                "sent_at": None,
            },
            "attempt_count_matches_status",
        ),
        (
            {
                "status": DeliveryStatus.RETRYING,
                "attempt_count": 1,
                "response_status": None,
                "last_error": None,
                "sent_at": None,
            },
            "failed_or_retrying_requires_error",
        ),
        (
            {
                "status": DeliveryStatus.PENDING,
                "attempt_count": 0,
                "response_status": 202,
                "last_error": None,
                "sent_at": None,
            },
            "pending_has_no_delivery_result",
        ),
        (
            {
                "status": DeliveryStatus.RETRYING,
                "attempt_count": 1,
                "response_status": 999,
                "last_error": "boom",
                "sent_at": None,
            },
            "response_status_http_bounds",
        ),
    ],
)
async def test_notification_delivery_state_constraints_are_enforced(
    factory,
    db_session,
    override: dict,
    expected_constraint: str,
) -> None:
    field = await factory.field()
    forecast = await factory.forecast(field=field, temp_min_c=-3)
    alert = await factory.alert(field=field, threshold_value=0)
    trigger = await factory.trigger(alert=alert, forecast=forecast, triggered_value=-3)
    values = {
        "trigger_id": trigger.id,
        "target_url": "http://mock-whatsapp.test/webhook/whatsapp",
        "status": DeliveryStatus.PENDING,
        "attempt_count": 0,
        "next_attempt_at": factory.frozen_time(),
        "last_error": None,
        "response_status": None,
        "sent_at": None,
        "created_at": factory.frozen_time(),
        "updated_at": factory.frozen_time(),
    }
    values.update(override)
    if values["status"] == DeliveryStatus.DELIVERED and values["sent_at"] is None and expected_constraint != "sent_at_matches_status":
        values["sent_at"] = factory.frozen_time()
    invalid_delivery = NotificationDelivery(**values)
    db_session.add(invalid_delivery)

    with pytest.raises(IntegrityError, match=expected_constraint):
        await db_session.commit()

    await db_session.rollback()
