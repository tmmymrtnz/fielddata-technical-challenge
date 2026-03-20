import pytest

from app.modules.alerts.evaluator import compare_metric
from app.modules.alerts.models import AlertOperator


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
def test_compare_metric(metric_value, operator, threshold, expected) -> None:
    assert compare_metric(metric_value, operator, threshold) is expected
