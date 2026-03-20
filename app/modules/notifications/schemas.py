from datetime import date, datetime

from pydantic import BaseModel

from app.modules.alerts.models import AlertMetric, AlertOperator
from app.modules.notifications.models import DeliveryStatus


class NotificationDeliveryRead(BaseModel):
    status: DeliveryStatus
    attempt_count: int
    response_status: int | None
    last_error: str | None
    sent_at: datetime | None
    next_attempt_at: datetime


class NotificationRead(BaseModel):
    trigger_id: int
    alert_id: int
    alert_name: str
    user_id: int
    field_id: int
    field_name: str
    forecast_date: date
    metric: AlertMetric
    operator: AlertOperator
    threshold_value: int
    triggered_value: int
    message: str
    created_at: datetime
    delivery: NotificationDeliveryRead | None
