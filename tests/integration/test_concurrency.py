from __future__ import annotations

from sqlalchemy import select

from app.modules.alerts.models import Alert
from app.modules.notifications.delivery import DeliveryResult
from app.modules.notifications.models import DeliveryStatus, NotificationDelivery
from app.worker.jobs import run_once


async def test_single_worker_updates_last_evaluated_at_only_for_active_alerts(
    factory,
    settings_factory,
    session_factory,
    frozen_time,
    monkeypatch,
) -> None:
    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    field = await factory.field()
    active_alert = await factory.alert(field=field, name="Active", lookahead_days=1)
    await factory.alert(field=field, name="Inactive", lookahead_days=1, is_active=False)
    await factory.alert(
        field=field,
        name="Deleted",
        lookahead_days=1,
        is_active=False,
        deleted_at=frozen_time(),
    )
    await factory.forecast(field=field, forecast_date=frozen_time.today(), temp_min_c=-3)

    stats = await run_once(session_factory=session_factory, settings=settings_factory())

    assert stats.evaluated_alerts == 1

    async with session_factory() as session:
        alerts = (await session.execute(select(Alert).order_by(Alert.id))).scalars().all()

    assert [alert.id for alert in alerts] == [active_alert.id, active_alert.id + 1, active_alert.id + 2]
    assert alerts[0].last_evaluated_at == frozen_time()
    assert alerts[1].last_evaluated_at is None
    assert alerts[2].last_evaluated_at is None


async def test_single_worker_processes_due_deliveries_across_multiple_batches(
    factory,
    settings_factory,
    session_factory,
    frozen_time,
    monkeypatch,
) -> None:
    delivered_trigger_ids: list[int] = []

    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        delivered_trigger_ids.append(payload["trigger_id"])
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    field = await factory.field()
    forecast = await factory.forecast(field=field, temp_min_c=-2)
    for index in range(3):
        alert = await factory.alert(field=field, name=f"Alert {index}", threshold_value=index)
        trigger = await factory.trigger(alert=alert, forecast=forecast, triggered_value=-2 - index)
        await factory.delivery(trigger=trigger, status=DeliveryStatus.PENDING, next_attempt_at=frozen_time())

    stats = await run_once(
        session_factory=session_factory,
        settings=settings_factory(worker_delivery_batch_size=2),
    )

    assert stats.delivered_notifications == 3
    assert delivered_trigger_ids == [1, 2, 3]

    async with session_factory() as session:
        deliveries = (
            await session.execute(select(NotificationDelivery).order_by(NotificationDelivery.id))
        ).scalars().all()

    assert [delivery.id for delivery in deliveries] == [1, 2, 3]
    assert all(delivery.status == DeliveryStatus.DELIVERED for delivery in deliveries)
    assert all(delivery.attempt_count == 1 for delivery in deliveries)
