from __future__ import annotations

from sqlalchemy import select

from app.modules.alerts.models import Alert, AlertMetric, AlertOperator, AlertTrigger
from app.modules.fields.models import Field
from app.modules.notifications.delivery import DeliveryResult
from app.modules.notifications.models import DeliveryStatus, NotificationDelivery
from app.worker.jobs import run_once


def _api_datetime(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def test_successful_delivery_exposes_payload_and_historical_snapshot(
    client,
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

    user = await factory.user(name="Alice", phone_number="+5491111111111")
    field = await factory.field(user=user, name="Campo Norte")
    await factory.forecast(field=field, forecast_date=frozen_time.today(), temp_min_c=-4)
    alert = await factory.alert(
        field=field,
        name="Helada Campo Norte",
        metric=AlertMetric.TEMP_MIN_C,
        threshold_value=0,
        lookahead_days=1,
    )

    stats = await run_once(session_factory=session_factory, settings=settings_factory())

    assert stats.delivered_notifications == 1
    assert delivered_payloads == [
        {
            "trigger_id": 1,
            "attempt_count": 1,
            "idempotency_key": "trigger-1",
            "user_id": user.id,
            "phone_number": user.phone_number,
            "field_name": "Campo Norte",
            "alert_name": "Helada Campo Norte",
            "forecast_date": frozen_time.today().isoformat(),
            "metric": "temp_min_c",
            "operator": "lte",
            "threshold_value": 0,
            "triggered_value": -4,
            "message": delivered_payloads[0]["message"],
        }
    ]
    assert "Helada Campo Norte" in delivered_payloads[0]["message"]

    async with session_factory() as session:
        stored_alert = await session.get(Alert, alert.id)
        stored_field = await session.get(Field, field.id)
        stored_alert.name = "Nombre nuevo"
        stored_field.name = "Campo Renombrado"
        await session.commit()

    response = await client.get(f"/notifications?user_id={user.id}")

    assert response.status_code == 200
    assert response.json() == [
        {
            "trigger_id": 1,
            "alert_id": alert.id,
            "alert_name": "Helada Campo Norte",
            "user_id": user.id,
            "field_id": field.id,
            "field_name": "Campo Norte",
            "forecast_date": frozen_time.today().isoformat(),
            "metric": "temp_min_c",
            "operator": "lte",
            "threshold_value": 0,
            "triggered_value": -4,
            "message": delivered_payloads[0]["message"],
            "created_at": _api_datetime(frozen_time()),
            "delivery": {
                "status": "delivered",
                "attempt_count": 1,
                "response_status": 202,
                "last_error": None,
                "sent_at": _api_datetime(frozen_time()),
                "next_attempt_at": _api_datetime(frozen_time()),
            },
        }
    ]


async def test_notifications_are_filtered_by_snapshot_user_id(
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

    first_user = await factory.user(name="Alice")
    second_user = await factory.user(name="Bob")
    first_field = await factory.field(user=first_user, name="Campo Norte")
    second_field = await factory.field(user=second_user, name="Lote Este")
    await factory.forecast(field=first_field, forecast_date=frozen_time.today(), temp_min_c=-2)
    await factory.forecast(field=second_field, forecast_date=frozen_time.today(), rain_mm=30)
    await factory.alert(field=first_field, name="Helada", metric=AlertMetric.TEMP_MIN_C, threshold_value=0, lookahead_days=1)
    await factory.alert(
        field=second_field,
        name="Lluvia",
        metric=AlertMetric.RAIN_MM,
        operator=AlertOperator.GTE,
        threshold_value=20,
        lookahead_days=1,
    )

    stats = await run_once(session_factory=session_factory, settings=settings_factory())

    assert stats.created_triggers == 2

    response = await client.get(f"/notifications?user_id={first_user.id}")

    assert response.status_code == 200
    assert [notification["user_id"] for notification in response.json()] == [first_user.id]
    assert [notification["alert_name"] for notification in response.json()] == ["Helada"]


async def test_transient_delivery_failure_retries_then_recovers(
    client,
    factory,
    frozen_time,
    settings_factory,
    session_factory,
    monkeypatch,
) -> None:
    attempts: list[int] = []

    async def flaky_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        attempts.append(payload["attempt_count"])
        if len(attempts) == 1:
            return DeliveryResult(success=False, response_status=503, error_message="temporary outage")
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", flaky_delivery)

    user = await factory.user()
    field = await factory.field(user=user)
    await factory.forecast(field=field, forecast_date=frozen_time.today(), rain_mm=25)
    await factory.alert(
        field=field,
        metric=AlertMetric.RAIN_MM,
        operator=AlertOperator.GTE,
        threshold_value=20,
        lookahead_days=1,
        name="Lluvia fuerte",
    )

    first_run = await run_once(session_factory=session_factory, settings=settings_factory())
    second_run_before_backoff = await run_once(session_factory=session_factory, settings=settings_factory())
    frozen_time.advance(minutes=1, seconds=1)
    third_run = await run_once(session_factory=session_factory, settings=settings_factory())

    assert first_run.created_triggers == 1
    assert first_run.delivered_notifications == 0
    assert first_run.failed_notifications == 0
    assert second_run_before_backoff.delivered_notifications == 0
    assert third_run.delivered_notifications == 1
    assert attempts == [1, 2]

    async with session_factory() as session:
        delivery = (await session.execute(select(NotificationDelivery))).scalar_one()

    assert delivery.status == DeliveryStatus.DELIVERED
    assert delivery.attempt_count == 2
    assert delivery.response_status == 202
    assert delivery.last_error is None
    assert delivery.sent_at == frozen_time()

    response = await client.get(f"/notifications?user_id={user.id}")

    assert response.status_code == 200
    assert response.json()[0]["delivery"]["status"] == "delivered"
    assert response.json()[0]["delivery"]["attempt_count"] == 2


async def test_delivery_exhausts_retries_and_stops_retrying(
    client,
    factory,
    frozen_time,
    settings_factory,
    session_factory,
    monkeypatch,
) -> None:
    call_count = 0

    async def failing_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        return DeliveryResult(success=False, response_status=500, error_message=f"boom-{call_count}")

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", failing_delivery)

    user = await factory.user()
    field = await factory.field(user=user)
    await factory.forecast(field=field, forecast_date=frozen_time.today(), wind_gust_mps=20)
    await factory.alert(
        field=field,
        metric=AlertMetric.WIND_GUST_MPS,
        operator=AlertOperator.GTE,
        threshold_value=15,
        lookahead_days=1,
    )

    first_run = await run_once(
        session_factory=session_factory,
        settings=settings_factory(delivery_max_retries=2, delivery_backoff_minutes="1,5"),
    )
    frozen_time.advance(minutes=1)
    second_run = await run_once(
        session_factory=session_factory,
        settings=settings_factory(delivery_max_retries=2, delivery_backoff_minutes="1,5"),
    )
    frozen_time.advance(minutes=10)
    third_run = await run_once(
        session_factory=session_factory,
        settings=settings_factory(delivery_max_retries=2, delivery_backoff_minutes="1,5"),
    )

    assert first_run.failed_notifications == 0
    assert second_run.failed_notifications == 1
    assert third_run.delivered_notifications == 0
    assert third_run.failed_notifications == 0
    assert call_count == 2

    async with session_factory() as session:
        delivery = (await session.execute(select(NotificationDelivery))).scalar_one()

    assert delivery.status == DeliveryStatus.FAILED
    assert delivery.attempt_count == 2
    assert delivery.response_status == 500
    assert delivery.last_error == "boom-2"

    response = await client.get(f"/notifications?user_id={user.id}")

    assert response.status_code == 200
    assert response.json()[0]["delivery"]["status"] == "failed"
    assert response.json()[0]["delivery"]["attempt_count"] == 2


async def test_trigger_messages_can_exceed_500_characters_without_breaking_persistence(
    factory,
    frozen_time,
    settings_factory,
    session_factory,
    monkeypatch,
) -> None:
    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    user = await factory.user(name="Alice", phone_number="+" + ("9" * 31))
    field = await factory.field(user=user, name="Campo " + ("N" * 249))
    await factory.forecast(field=field, forecast_date=frozen_time.today(), rain_probability_pct=90)
    await factory.alert(
        field=field,
        name="Alerta " + ("L" * 248),
        metric=AlertMetric.RAIN_PROBABILITY_PCT,
        operator=AlertOperator.GTE,
        threshold_value=80,
        lookahead_days=1,
    )

    stats = await run_once(session_factory=session_factory, settings=settings_factory())

    assert stats.created_triggers == 1
    assert stats.delivered_notifications == 1

    async with session_factory() as session:
        trigger = (await session.execute(select(AlertTrigger))).scalar_one()

    assert len(trigger.message) > 500
