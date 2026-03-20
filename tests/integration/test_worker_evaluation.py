from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.modules.alerts.models import AlertMetric, AlertOperator, AlertTrigger
from app.modules.notifications.delivery import DeliveryResult
from app.modules.notifications.models import NotificationDelivery
from app.modules.weather.models import WeatherForecast
from app.worker.jobs import run_once


@pytest.mark.parametrize(
    ("metric", "operator", "threshold", "forecast_value"),
    [
        (AlertMetric.TEMP_MIN_C, AlertOperator.LTE, 0, -2),
        (AlertMetric.TEMP_MAX_C, AlertOperator.GTE, 20, 21),
        (AlertMetric.RAIN_MM, AlertOperator.GTE, 10, 12),
        (AlertMetric.RAIN_PROBABILITY_PCT, AlertOperator.GTE, 60, 60),
        (AlertMetric.SNOW_MM, AlertOperator.GTE, 2, 3),
        (AlertMetric.SNOW_PROBABILITY_PCT, AlertOperator.GTE, 40, 50),
        (AlertMetric.WIND_SPEED_MPS, AlertOperator.GTE, 8, 9),
        (AlertMetric.WIND_GUST_MPS, AlertOperator.GTE, 12, 13),
    ],
)
async def test_worker_supports_each_metric_integration(
    factory,
    frozen_time,
    settings_factory,
    session_factory,
    monkeypatch,
    metric: AlertMetric,
    operator: AlertOperator,
    threshold: int,
    forecast_value: int,
) -> None:
    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    user = await factory.user()
    field = await factory.field(user=user)
    alert = await factory.alert(field=field, metric=metric, operator=operator, threshold_value=threshold, lookahead_days=2)
    await factory.forecast(field=field, forecast_date=frozen_time.today(), **{metric.value: forecast_value})

    stats = await run_once(session_factory=session_factory, settings=settings_factory())

    assert stats.evaluated_alerts == 1
    assert stats.created_triggers == 1
    assert stats.delivered_notifications == 1

    async with session_factory() as session:
        trigger = (
            await session.execute(select(AlertTrigger).where(AlertTrigger.alert_id == alert.id))
        ).scalar_one()

    assert trigger.metric_snapshot == metric
    assert trigger.operator_snapshot == operator
    assert trigger.threshold_value_snapshot == threshold
    assert trigger.triggered_value == forecast_value


async def test_lookahead_is_exact_and_multiple_alerts_create_independent_triggers(
    factory,
    frozen_time,
    settings_factory,
    session_factory,
    monkeypatch,
) -> None:
    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    user = await factory.user()
    field = await factory.field(user=user, name="Campo Norte")
    today = frozen_time.today()
    await factory.forecast(field=field, forecast_date=today, rain_mm=15, rain_probability_pct=75)
    await factory.forecast(field=field, forecast_date=today + timedelta(days=1), rain_mm=18, rain_probability_pct=80)
    outside_forecast = await factory.forecast(
        field=field,
        forecast_date=today + timedelta(days=2),
        rain_mm=21,
        rain_probability_pct=85,
    )
    first_alert = await factory.alert(
        field=field,
        name="Rain total",
        metric=AlertMetric.RAIN_MM,
        operator=AlertOperator.GTE,
        threshold_value=10,
        lookahead_days=2,
    )
    second_alert = await factory.alert(
        field=field,
        name="Rain chance",
        metric=AlertMetric.RAIN_PROBABILITY_PCT,
        operator=AlertOperator.GTE,
        threshold_value=70,
        lookahead_days=2,
    )

    stats = await run_once(session_factory=session_factory, settings=settings_factory())

    assert stats.created_triggers == 4
    assert stats.delivered_notifications == 4

    async with session_factory() as session:
        triggers = (
            await session.execute(select(AlertTrigger).order_by(AlertTrigger.alert_id, AlertTrigger.forecast_date_snapshot))
        ).scalars().all()

    assert [(trigger.alert_id, trigger.forecast_date_snapshot) for trigger in triggers] == [
        (first_alert.id, today),
        (first_alert.id, today + timedelta(days=1)),
        (second_alert.id, today),
        (second_alert.id, today + timedelta(days=1)),
    ]
    assert all(trigger.weather_forecast_id != outside_forecast.id for trigger in triggers)


async def test_inactive_deleted_and_null_metric_alerts_do_not_trigger(
    factory,
    frozen_time,
    settings_factory,
    session_factory,
    monkeypatch,
) -> None:
    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    user = await factory.user()
    field = await factory.field(user=user)
    await factory.forecast(field=field, forecast_date=frozen_time.today(), wind_gust_mps=None, temp_min_c=-3)
    active_alert = await factory.alert(field=field, metric=AlertMetric.TEMP_MIN_C, threshold_value=0, lookahead_days=1)
    await factory.alert(field=field, metric=AlertMetric.TEMP_MIN_C, threshold_value=0, lookahead_days=1, is_active=False)
    await factory.alert(
        field=field,
        metric=AlertMetric.TEMP_MIN_C,
        threshold_value=0,
        lookahead_days=1,
        deleted_at=frozen_time(),
    )
    await factory.alert(
        field=field,
        metric=AlertMetric.WIND_GUST_MPS,
        operator=AlertOperator.GTE,
        threshold_value=12,
        lookahead_days=1,
    )

    stats = await run_once(session_factory=session_factory, settings=settings_factory())

    assert stats.created_triggers == 1

    async with session_factory() as session:
        triggers = (await session.execute(select(AlertTrigger))).scalars().all()

    assert [trigger.alert_id for trigger in triggers] == [active_alert.id]


async def test_worker_rerun_does_not_duplicate_triggers_or_deliveries(
    factory,
    frozen_time,
    settings_factory,
    session_factory,
    monkeypatch,
) -> None:
    delivered_payloads: list[dict] = []

    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        delivered_payloads.append(payload)
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    user = await factory.user()
    field = await factory.field(user=user)
    await factory.forecast(field=field, forecast_date=frozen_time.today(), rain_mm=22)
    alert = await factory.alert(
        field=field,
        metric=AlertMetric.RAIN_MM,
        operator=AlertOperator.GTE,
        threshold_value=20,
        lookahead_days=1,
    )

    first_run = await run_once(session_factory=session_factory, settings=settings_factory())
    second_run = await run_once(session_factory=session_factory, settings=settings_factory())

    assert first_run.created_triggers == 1
    assert first_run.delivered_notifications == 1
    assert second_run.created_triggers == 0
    assert second_run.delivered_notifications == 0
    assert [payload["idempotency_key"] for payload in delivered_payloads] == ["trigger-1"]

    async with session_factory() as session:
        triggers = (
            await session.execute(select(AlertTrigger).where(AlertTrigger.alert_id == alert.id))
        ).scalars().all()
        deliveries = (await session.execute(select(NotificationDelivery))).scalars().all()

    assert len(triggers) == 1
    assert len(deliveries) == 1


async def test_editing_alert_reevaluates_without_duplicating_existing_trigger(
    client,
    factory,
    frozen_time,
    settings_factory,
    session_factory,
    monkeypatch,
) -> None:
    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    user = await factory.user()
    field = await factory.field(user=user)
    today = frozen_time.today()
    await factory.forecast(field=field, forecast_date=today, temp_min_c=-1)
    await factory.forecast(field=field, forecast_date=today + timedelta(days=1), temp_min_c=2)
    alert = await factory.alert(
        field=field,
        metric=AlertMetric.TEMP_MIN_C,
        operator=AlertOperator.LTE,
        threshold_value=0,
        lookahead_days=2,
    )

    first_run = await run_once(session_factory=session_factory, settings=settings_factory())
    update_response = await client.patch(
        f"/alerts/{alert.id}?user_id={user.id}",
        json={"threshold_value": 2},
    )
    second_run = await run_once(session_factory=session_factory, settings=settings_factory())

    assert first_run.created_triggers == 1
    assert update_response.status_code == 200
    assert second_run.created_triggers == 1

    async with session_factory() as session:
        triggers = (
            await session.execute(select(AlertTrigger).where(AlertTrigger.alert_id == alert.id).order_by(AlertTrigger.forecast_date_snapshot))
        ).scalars().all()

    assert [trigger.forecast_date_snapshot for trigger in triggers] == [today, today + timedelta(days=1)]


async def test_forecast_update_can_create_new_trigger_but_never_duplicate_existing_one(
    factory,
    frozen_time,
    settings_factory,
    session_factory,
    monkeypatch,
) -> None:
    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    user = await factory.user()
    field = await factory.field(user=user)
    forecast = await factory.forecast(field=field, forecast_date=frozen_time.today(), rain_mm=5)
    alert = await factory.alert(
        field=field,
        metric=AlertMetric.RAIN_MM,
        operator=AlertOperator.GTE,
        threshold_value=10,
        lookahead_days=1,
    )

    first_run = await run_once(session_factory=session_factory, settings=settings_factory())
    forecast.rain_mm = 10
    await factory.session.commit()
    frozen_time.advance(minutes=1, seconds=1)
    second_run = await run_once(session_factory=session_factory, settings=settings_factory())
    forecast.rain_mm = 14
    await factory.session.commit()
    frozen_time.advance(minutes=1, seconds=1)
    third_run = await run_once(session_factory=session_factory, settings=settings_factory())

    assert first_run.created_triggers == 0
    assert second_run.created_triggers == 1
    assert third_run.created_triggers == 0

    async with session_factory() as session:
        triggers = (
            await session.execute(select(AlertTrigger).where(AlertTrigger.alert_id == alert.id))
        ).scalars().all()
        stored_forecast = await session.get(WeatherForecast, forecast.id)

    assert len(triggers) == 1
    assert stored_forecast is not None
    assert stored_forecast.rain_mm == 14


async def test_small_worker_batches_do_not_change_functional_result(
    factory,
    frozen_time,
    settings_factory,
    session_factory,
    monkeypatch,
) -> None:
    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    user = await factory.user()
    field = await factory.field(user=user)
    for offset in range(3):
        await factory.forecast(field=field, forecast_date=frozen_time.today() + timedelta(days=offset), wind_speed_mps=10 + offset)
        await factory.alert(
            field=field,
            name=f"Wind {offset}",
            metric=AlertMetric.WIND_SPEED_MPS,
            operator=AlertOperator.GTE,
            threshold_value=10 + offset,
            lookahead_days=3,
        )

    stats = await run_once(
        session_factory=session_factory,
        settings=settings_factory(worker_delivery_batch_size=1),
    )

    assert stats.evaluated_alerts == 3
    assert stats.created_triggers == 6
    assert stats.delivered_notifications == 6

    async with session_factory() as session:
        trigger_count = (await session.execute(select(AlertTrigger))).scalars().all()
        delivery_count = (await session.execute(select(NotificationDelivery))).scalars().all()

    assert len(trigger_count) == 6
    assert len(delivery_count) == 6
