from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.modules.alerts.models import AlertMetric, AlertOperator
from app.modules.alerts.validation import ensure_threshold_value_is_valid


class AlertCreate(BaseModel):
    user_id: int
    field_id: int
    name: str = Field(min_length=1, max_length=255)
    metric: AlertMetric
    operator: AlertOperator
    threshold_value: int
    lookahead_days: int = Field(ge=1, le=30)

    @model_validator(mode="after")
    def validate_threshold_value(self) -> "AlertCreate":
        ensure_threshold_value_is_valid(self.metric, self.threshold_value)
        return self


class AlertUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    metric: AlertMetric | None = None
    operator: AlertOperator | None = None
    threshold_value: int | None = None
    lookahead_days: int | None = Field(default=None, ge=1, le=30)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_threshold_value(self) -> "AlertUpdate":
        if self.metric is None or self.threshold_value is None:
            return self

        ensure_threshold_value_is_valid(self.metric, self.threshold_value)
        return self


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
