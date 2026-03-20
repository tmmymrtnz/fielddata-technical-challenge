from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.alerts.models import AlertMetric, AlertOperator


class AlertCreate(BaseModel):
    user_id: int
    field_id: int
    name: str = Field(min_length=1, max_length=255)
    metric: AlertMetric
    operator: AlertOperator
    threshold_value: int
    lookahead_days: int = Field(ge=1, le=30)


class AlertUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    metric: AlertMetric | None = None
    operator: AlertOperator | None = None
    threshold_value: int | None = None
    lookahead_days: int | None = Field(default=None, ge=1, le=30)
    is_active: bool | None = None


class AlertRead(BaseModel):
    id: int
    field_id: int
    user_id: int
    name: str
    metric: AlertMetric
    operator: AlertOperator
    threshold_value: int
    lookahead_days: int
    is_active: bool
    last_evaluated_at: datetime | None
    created_at: datetime
    updated_at: datetime
