from __future__ import annotations

import pytest
from pydantic_core import PydanticCustomError

from app.modules.alerts.models import AlertMetric
from app.modules.alerts.validation import ensure_threshold_value_is_valid


@pytest.mark.parametrize(
    ("metric", "threshold_value"),
    [
        (AlertMetric.RAIN_PROBABILITY_PCT, 0),
        (AlertMetric.RAIN_PROBABILITY_PCT, 100),
        (AlertMetric.RAIN_MM, 0),
        (AlertMetric.WIND_GUST_MPS, 12),
        (AlertMetric.TEMP_MIN_C, -5),
    ],
)
def test_threshold_validation_accepts_valid_metric_threshold_combinations(
    metric: AlertMetric,
    threshold_value: int,
) -> None:
    ensure_threshold_value_is_valid(metric, threshold_value)


@pytest.mark.parametrize(
    ("metric", "threshold_value", "error_type"),
    [
        (AlertMetric.RAIN_PROBABILITY_PCT, 150, "threshold_probability_bounds"),
        (AlertMetric.SNOW_PROBABILITY_PCT, -1, "threshold_probability_bounds"),
        (AlertMetric.RAIN_MM, -1, "threshold_non_negative_for_metric"),
        (AlertMetric.WIND_SPEED_MPS, -1, "threshold_non_negative_for_metric"),
    ],
)
def test_threshold_validation_rejects_invalid_metric_threshold_combinations(
    metric: AlertMetric,
    threshold_value: int,
    error_type: str,
) -> None:
    with pytest.raises(PydanticCustomError) as exc_info:
        ensure_threshold_value_is_valid(metric, threshold_value)

    assert exc_info.value.type == error_type
