from app.modules.alerts.models import AlertOperator


def compare_metric(metric_value: int | None, operator: AlertOperator, threshold_value: int) -> bool:
    if metric_value is None:
        return False
    if operator == AlertOperator.LT:
        return metric_value < threshold_value
    if operator == AlertOperator.LTE:
        return metric_value <= threshold_value
    if operator == AlertOperator.GT:
        return metric_value > threshold_value
    if operator == AlertOperator.GTE:
        return metric_value >= threshold_value
    raise ValueError(f"Unsupported operator: {operator}")
