from __future__ import annotations

from pydantic import BaseModel, model_validator
from pydantic_core import PydanticCustomError

from app.modules.alerts.models import AlertMetric


PROBABILITY_METRICS = {
    AlertMetric.RAIN_PROBABILITY_PCT,
    AlertMetric.SNOW_PROBABILITY_PCT,
}

NON_NEGATIVE_THRESHOLD_METRICS = PROBABILITY_METRICS | {
    AlertMetric.RAIN_MM,
    AlertMetric.SNOW_MM,
    AlertMetric.WIND_SPEED_MPS,
    AlertMetric.WIND_GUST_MPS,
}


def ensure_threshold_value_is_valid(metric: AlertMetric, threshold_value: int) -> None:
    if metric in PROBABILITY_METRICS and not 0 <= threshold_value <= 100:
        raise PydanticCustomError(
            "threshold_probability_bounds",
            "threshold_value debe estar entre 0 y 100 para métricas de probabilidad",
        )

    if metric in NON_NEGATIVE_THRESHOLD_METRICS and threshold_value < 0:
        raise PydanticCustomError(
            "threshold_non_negative_for_metric",
            "threshold_value debe ser >= 0 para esta métrica",
        )


class AlertThresholdSettings(BaseModel):
    metric: AlertMetric
    threshold_value: int

    @model_validator(mode="after")
    def validate_threshold_value(self) -> "AlertThresholdSettings":
        ensure_threshold_value_is_valid(self.metric, self.threshold_value)
        return self
