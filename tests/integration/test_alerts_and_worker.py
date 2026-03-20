from __future__ import annotations

from app.core.config import Settings
from app.modules.notifications.delivery import DeliveryResult
from app.worker.jobs import run_once


async def test_create_alert_run_worker_and_list_notifications(client, session_factory, seeded_entities, monkeypatch) -> None:
    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    payload = {
        "user_id": seeded_entities["user_id"],
        "field_id": seeded_entities["field_id"],
        "name": "Helada Test",
        "metric": "temp_min_c",
        "operator": "lte",
        "threshold_value": 0,
        "lookahead_days": 2,
    }
    create_response = await client.post("/alerts", json=payload)
    assert create_response.status_code == 201

    stats = await run_once(
        session_factory=session_factory,
        settings=Settings(
            database_url="sqlite+aiosqlite:///unused.db",
            mock_whatsapp_url="http://mock-whatsapp.test/webhook/whatsapp",
            delivery_max_retries=3,
            delivery_backoff_minutes="1,5,15",
        ),
    )
    assert stats.created_triggers == 1
    assert stats.delivered_notifications == 1

    notifications_response = await client.get(f"/notifications?user_id={seeded_entities['user_id']}")
    assert notifications_response.status_code == 200
    notifications = notifications_response.json()
    assert len(notifications) == 1
    assert notifications[0]["alert_name"] == "Helada Test"
    assert notifications[0]["delivery"]["status"] == "delivered"


async def test_worker_rerun_does_not_duplicate_triggers_or_deliveries(
    client,
    session_factory,
    seeded_entities,
    monkeypatch,
) -> None:
    async def fake_delivery(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:  # noqa: ARG001
        return DeliveryResult(success=True, response_status=202, error_message=None)

    monkeypatch.setattr("app.worker.jobs.deliver_webhook", fake_delivery)

    payload = {
        "user_id": seeded_entities["user_id"],
        "field_id": seeded_entities["field_id"],
        "name": "Lluvia Test",
        "metric": "rain_mm",
        "operator": "gte",
        "threshold_value": 10,
        "lookahead_days": 2,
    }
    create_response = await client.post("/alerts", json=payload)
    assert create_response.status_code == 201

    settings = Settings(
        database_url="sqlite+aiosqlite:///unused.db",
        mock_whatsapp_url="http://mock-whatsapp.test/webhook/whatsapp",
        delivery_max_retries=3,
        delivery_backoff_minutes="1,5,15",
        worker_interval_minutes=1,
    )

    first_run = await run_once(session_factory=session_factory, settings=settings)
    second_run = await run_once(session_factory=session_factory, settings=settings)

    assert first_run.created_triggers == 1
    assert first_run.delivered_notifications == 1
    assert second_run.created_triggers == 0
    assert second_run.delivered_notifications == 0

    notifications_response = await client.get(f"/notifications?user_id={seeded_entities['user_id']}")
    assert notifications_response.status_code == 200
    notifications = notifications_response.json()
    assert len(notifications) == 1
    assert notifications[0]["alert_name"] == "Lluvia Test"


async def test_soft_delete_alert_hides_it_from_list(client, seeded_entities) -> None:
    payload = {
        "user_id": seeded_entities["user_id"],
        "field_id": seeded_entities["field_id"],
        "name": "Viento Test",
        "metric": "wind_gust_mps",
        "operator": "gte",
        "threshold_value": 12,
        "lookahead_days": 3,
    }
    create_response = await client.post("/alerts", json=payload)
    alert_id = create_response.json()["id"]

    delete_response = await client.delete(f"/alerts/{alert_id}?user_id={seeded_entities['user_id']}")
    assert delete_response.status_code == 204

    list_response = await client.get(f"/alerts?user_id={seeded_entities['user_id']}")
    assert list_response.status_code == 200
    assert list_response.json() == []
