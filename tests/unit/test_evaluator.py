from __future__ import annotations

from datetime import date

import pytest

from app.modules.alerts.evaluator import compare_metric
from app.modules.alerts.models import Alert, AlertMetric, AlertOperator
from app.modules.alerts.service import forecast_matches_alert
from app.modules.weather.models import WeatherForecast


@pytest.mark.parametrize(
    ("metric_value", "operator", "threshold", "expected"),
    [
        (None, AlertOperator.GTE, 10, False),
        (10, AlertOperator.GTE, 10, True),
        (9, AlertOperator.GTE, 10, False),
        (9, AlertOperator.GT, 10, False),
        (11, AlertOperator.GT, 10, True),
        (10, AlertOperator.LTE, 10, True),
        (11, AlertOperator.LTE, 10, False),
        (9, AlertOperator.LT, 10, True),
        (10, AlertOperator.LT, 10, False),
    ],
)
def test_compare_metric(metric_value: int | None, operator: AlertOperator, threshold: int, expected: bool) -> None:
    assert compare_metric(metric_value, operator, threshold) is expected


@pytest.mark.parametrize(
    ("metric", "operator", "threshold", "value", "expected"),
    [
        (AlertMetric.TEMP_MIN_C, AlertOperator.LTE, 0, -2, True),
        (AlertMetric.TEMP_MAX_C, AlertOperator.GTE, 20, 19, False),
        (AlertMetric.RAIN_MM, AlertOperator.GTE, 12, 12, True),
        (AlertMetric.RAIN_PROBABILITY_PCT, AlertOperator.GT, 50, 50, False),
        (AlertMetric.SNOW_MM, AlertOperator.GTE, 1, 3, True),
        (AlertMetric.SNOW_PROBABILITY_PCT, AlertOperator.LT, 40, 39, True),
        (AlertMetric.WIND_SPEED_MPS, AlertOperator.GTE, 8, 8, True),
        (AlertMetric.WIND_GUST_MPS, AlertOperator.GTE, 15, None, False),
    ],
)
def test_forecast_matches_alert_uses_requested_metric(
    metric: AlertMetric,
    operator: AlertOperator,
    threshold: int,
    value: int | None,
    expected: bool,
) -> None:
    alert = Alert(
        field_id=1,
        name="Factory Alert",
        metric=metric,
        operator=operator,
        threshold_value=threshold,
        lookahead_days=3,
        is_active=True,
    )
    forecast = WeatherForecast(
        field_id=1,
        forecast_date=date(2026, 3, 20),
        temp_min_c=-2,
        temp_max_c=18,
        rain_mm=12,
        rain_probability_pct=50,
        snow_mm=3,
        snow_probability_pct=39,
        wind_speed_mps=8,
        wind_gust_mps=value,
        raw_payload={"unit": True},
    )

    matches, matched_value = forecast_matches_alert(alert, forecast)
    expected_value = value if metric == AlertMetric.WIND_GUST_MPS else getattr(forecast, metric.value)

    assert matches is expected
    assert matched_value == expected_value
