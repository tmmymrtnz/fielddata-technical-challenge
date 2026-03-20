from __future__ import annotations

import asyncio
import logging
from datetime import date

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.notifications.delivery import close_delivery_clients, deliver_webhook
from app.worker.jobs import PendingDelivery, WorkerRunStats, _backoff_minutes, _delivery_payload
from app.worker.main import worker_loop


def test_backoff_minutes_clamps_to_last_configured_value() -> None:
    settings = Settings(delivery_backoff_minutes="1,5,15")

    assert _backoff_minutes(settings, 1) == 1
    assert _backoff_minutes(settings, 2) == 5
    assert _backoff_minutes(settings, 3) == 15
    assert _backoff_minutes(settings, 9) == 15


def test_delivery_payload_contains_observable_delivery_fields() -> None:
    payload = _delivery_payload(
        PendingDelivery(
            delivery_id=9,
            trigger_id=42,
            target_url="http://mock-whatsapp.test/webhook/whatsapp",
            attempt_count=1,
            user_id=7,
            phone_number="+5493000000007",
            field_name="Campo Norte",
            alert_name="Helada",
            forecast_date=date(2026, 3, 21),
            metric="temp_min_c",
            operator="lte",
            threshold_value=0,
            triggered_value=-3,
            message="Alert payload",
        )
    )

    assert payload == {
        "trigger_id": 42,
        "attempt_count": 2,
        "idempotency_key": "trigger-42",
        "user_id": 7,
        "phone_number": "+5493000000007",
        "field_name": "Campo Norte",
        "alert_name": "Helada",
        "forecast_date": "2026-03-21",
        "metric": "temp_min_c",
        "operator": "lte",
        "threshold_value": 0,
        "triggered_value": -3,
        "message": "Alert payload",
    }


def test_settings_reject_invalid_runtime_configuration() -> None:
    with pytest.raises(ValidationError):
        Settings(worker_interval_minutes=0)

    with pytest.raises(ValidationError):
        Settings(request_timeout_seconds=0)

    with pytest.raises(ValidationError):
        Settings(delivery_backoff_minutes="0,-1")

    with pytest.raises(ValidationError):
        Settings(log_level="LOUD")


@pytest.mark.asyncio
async def test_deliver_webhook_reuses_http_client_within_the_same_event_loop(monkeypatch) -> None:
    created_clients: list[FakeAsyncClient] = []

    class FakeResponse:
        status_code = 202

    class FakeAsyncClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
            self.calls: list[tuple[str, dict]] = []
            self.is_closed = False
            created_clients.append(self)

        async def post(self, url: str, json: dict) -> FakeResponse:
            self.calls.append((url, json))
            return FakeResponse()

        async def aclose(self) -> None:
            self.is_closed = True

    monkeypatch.setattr("app.modules.notifications.delivery.httpx.AsyncClient", FakeAsyncClient)

    first = await deliver_webhook("http://mock-whatsapp.test/webhook/whatsapp", {"attempt": 1}, 10)
    second = await deliver_webhook("http://mock-whatsapp.test/webhook/whatsapp", {"attempt": 2}, 10)

    assert first.success is True
    assert second.success is True
    assert len(created_clients) == 1
    assert created_clients[0].calls == [
        ("http://mock-whatsapp.test/webhook/whatsapp", {"attempt": 1}),
        ("http://mock-whatsapp.test/webhook/whatsapp", {"attempt": 2}),
    ]

    await close_delivery_clients()


@pytest.mark.asyncio
async def test_worker_loop_logs_and_retries_after_a_failed_cycle(monkeypatch, caplog) -> None:
    calls = 0
    sleep_calls: list[int | float] = []
    settings = Settings(worker_failure_backoff_seconds=3)

    async def fake_run_once(*, settings: Settings | None = None, session_factory=None):  # noqa: ARG001
        nonlocal calls
        assert settings is not None
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        if calls == 2:
            return WorkerRunStats(evaluated_alerts=1, created_triggers=2, delivered_notifications=3, failed_notifications=0)
        raise asyncio.CancelledError

    async def fake_sleep(seconds: int | float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("app.worker.main.run_once", fake_run_once)
    monkeypatch.setattr("app.worker.main.asyncio.sleep", fake_sleep)

    with caplog.at_level(logging.INFO):
        with pytest.raises(asyncio.CancelledError):
            await worker_loop(1, settings=settings)

    assert sleep_calls[0] == 3
    assert sleep_calls[1] == pytest.approx(60, abs=0.1)
    assert "Worker cycle failed" in caplog.text
    assert "Worker cycle completed" in caplog.text
