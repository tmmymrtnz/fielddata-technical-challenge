from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("mock_whatsapp")

app = FastAPI(title="Mock WhatsApp Webhook")
failed_once: set[int] = set()


class MockNotification(BaseModel):
    trigger_id: int
    attempt_count: int
    user_id: int
    phone_number: str
    field_name: str
    alert_name: str
    forecast_date: str
    metric: str
    operator: str
    threshold_value: int
    triggered_value: int
    message: str


@app.post("/webhook/whatsapp", status_code=202)
async def receive_notification(payload: MockNotification) -> dict[str, str]:
    if settings.mock_whatsapp_fail_first_delivery and payload.trigger_id not in failed_once:
        failed_once.add(payload.trigger_id)
        raise HTTPException(status_code=500, detail="Simulated first delivery failure")

    logger.info(
        "Mock WhatsApp delivery user_id=%s phone=%s alert=%s message=%s",
        payload.user_id,
        payload.phone_number,
        payload.alert_name,
        payload.message,
    )
    return {"status": "accepted"}
