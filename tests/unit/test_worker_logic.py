from __future__ import annotations

from datetime import date

from app.core.config import Settings
from app.worker.jobs import PendingDelivery, _backoff_minutes, _delivery_payload


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
