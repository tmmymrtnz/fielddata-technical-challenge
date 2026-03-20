from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.modules.alerts.models import Alert, AlertTrigger
from app.modules.notifications.delivery import DeliveryResult
from app.modules.notifications.models import DeliveryStatus, NotificationDelivery
from app.worker.jobs import _claim_alert_batch_ids, _claim_delivery_batch, run_once


@pytest.mark.concurrency
async def test_alert_claiming_is_disjoint_across_concurrent_workers(
    factory,
    settings_factory,
    session_factory,
    frozen_time,
) -> None:
    field = await factory.field()
    for index in range(4):
        await factory.alert(field=field, name=f"Alert {index}", lookahead_days=1)

    settings = settings_factory(worker_alert_batch_size=2)
    first_claim, second_claim = await asyncio.gather(
        _claim_alert_batch_ids(session_factory, settings),
        _claim_alert_batch_ids(session_factory, settings),
    )

    assert len(first_claim) == 2
    assert len(second_claim) == 2
    assert set(first_claim).isdisjoint(second_claim)
    assert len(set(first_claim + second_claim)) == 4

    async with session_factory() as session:
        alerts = (await session.execute(select(Alert).order_by(Alert.id))).scalars().all()

    assert [alert.id for alert in alerts] == [1, 2, 3, 4]
    assert all(alert.last_evaluated_at == frozen_time() for alert in alerts)


@pytest.mark.concurrency
async def test_delivery_claiming_is_disjoint_across_concurrent_workers(
    factory,
    settings_factory,
    session_factory,
    frozen_time,
) -> None:
    field = await factory.field()
    forecast = await factory.forecast(field=field, temp_min_c=-2)
    for index in range(4):
        alert = await factory.alert(field=field, name=f"Alert {index}", threshold_value=0)
        trigger = await factory.trigger(alert=alert, forecast=forecast, triggered_value=-2 - index)
        await factory.delivery(trigger=trigger, status=DeliveryStatus.PENDING, next_attempt_at=frozen_time())

    settings = settings_factory(worker_delivery_batch_size=2, delivery_claim_ttl_seconds=120)
    first_batch, second_batch = await asyncio.gather(
        _claim_delivery_batch(session_factory, settings),
        _claim_delivery_batch(session_factory, settings),
    )

    first_ids = {delivery.delivery_id for delivery in first_batch}
    second_ids = {delivery.delivery_id for delivery in second_batch}

    assert len(first_ids) == 2
    assert len(second_ids) == 2
    assert first_ids.isdisjoint(second_ids)

    async with session_factory() as session:
        deliveries = (
            await session.execute(select(NotificationDelivery).order_by(NotificationDelivery.id))
        ).scalars().all()

    assert [delivery.id for delivery in deliveries] == [1, 2, 3, 4]
    assert all(delivery.next_attempt_at == frozen_time() + timedelta(seconds=120) for delivery in deliveries)


@pytest.mark.concurrency
async def test_concurrent_run_once_does_not_duplicate_observable_delivery(
    factory,
    settings_factory,
    session_factory,
    frozen_time,
    monkeypatch,
) -> None:
    delivered_trigger_ids: list[int] = []

    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        await asyncio.sleep(0.05)
        delivered_trigger_ids.append(payload["trigger_id"])
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    field = await factory.field()
    await factory.forecast(field=field, forecast_date=frozen_time.today(), temp_min_c=-3)
    await factory.alert(field=field, threshold_value=0, lookahead_days=1)

    first_run, second_run = await asyncio.gather(
        run_once(session_factory=session_factory, settings=settings_factory(worker_alert_batch_size=1, worker_delivery_batch_size=1)),
        run_once(session_factory=session_factory, settings=settings_factory(worker_alert_batch_size=1, worker_delivery_batch_size=1)),
    )

    assert first_run.created_triggers + second_run.created_triggers == 1
    assert delivered_trigger_ids == [1]

    async with session_factory() as session:
        trigger_count = (await session.execute(select(AlertTrigger))).scalars().all()
        delivery_count = (await session.execute(select(NotificationDelivery))).scalars().all()

    assert len(trigger_count) == 1
    assert len(delivery_count) == 1
