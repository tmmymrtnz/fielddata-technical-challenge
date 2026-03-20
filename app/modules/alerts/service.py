from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.alerts.evaluator import compare_metric
from app.modules.alerts.models import Alert, AlertTrigger
from app.modules.fields.models import Field
from app.modules.notifications.models import DeliveryStatus, NotificationDelivery
from app.modules.users.models import User
from app.modules.weather.models import WeatherForecast
from app.db.base import utcnow


def get_metric_value(forecast: WeatherForecast, metric_name: str) -> int | None:
    return getattr(forecast, metric_name)


def build_trigger_message(
    user: User,
    field: Field,
    alert: Alert,
    forecast: WeatherForecast,
    triggered_value: int,
) -> str:
    return (
        f"Alert '{alert.name}' for user {user.id} ({user.phone_number}) on field '{field.name}': "
        f"{alert.metric.value}={triggered_value} {alert.operator.value} {alert.threshold_value} "
        f"for {forecast.forecast_date.isoformat()}"
    )


def active_alerts_query() -> Select[tuple[Alert]]:
    return (
        select(Alert)
        .where(Alert.is_active.is_(True), Alert.deleted_at.is_(None))
        .options(joinedload(Alert.field).joinedload(Field.user))
        .order_by(Alert.id)
    )


def active_forecasts_query(alert: Alert, today: date) -> Select[tuple[WeatherForecast]]:
    return (
        select(WeatherForecast)
        .where(
            WeatherForecast.field_id == alert.field_id,
            WeatherForecast.forecast_date >= today,
            WeatherForecast.forecast_date < today + timedelta(days=alert.lookahead_days),
        )
        .order_by(WeatherForecast.forecast_date)
    )


async def get_field_for_user(session: AsyncSession, field_id: int, user_id: int) -> Field | None:
    result = await session.execute(select(Field).where(Field.id == field_id, Field.user_id == user_id))
    return result.scalar_one_or_none()


async def get_alert_for_user(session: AsyncSession, alert_id: int, user_id: int, include_deleted: bool = False) -> Alert | None:
    query = (
        select(Alert)
        .join(Alert.field)
        .options(joinedload(Alert.field))
        .where(Alert.id == alert_id, Field.user_id == user_id)
    )
    if not include_deleted:
        query = query.where(Alert.deleted_at.is_(None))
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def require_field_for_user(session: AsyncSession, field_id: int, user_id: int) -> Field:
    field = await get_field_for_user(session, field_id, user_id)
    if field is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found for user")
    return field


async def require_alert_for_user(session: AsyncSession, alert_id: int, user_id: int) -> Alert:
    alert = await get_alert_for_user(session, alert_id, user_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found for user")
    return alert


def alert_to_read(alert: Alert) -> dict:
    return {
        "id": alert.id,
        "field_id": alert.field_id,
        "user_id": alert.field.user_id,
        "name": alert.name,
        "metric": alert.metric,
        "operator": alert.operator,
        "threshold_value": alert.threshold_value,
        "lookahead_days": alert.lookahead_days,
        "is_active": alert.is_active,
        "last_evaluated_at": alert.last_evaluated_at,
        "created_at": alert.created_at,
        "updated_at": alert.updated_at,
    }


def build_trigger_snapshot(alert: Alert, forecast: WeatherForecast, value: int) -> dict:
    now = utcnow()
    return {
        "alert_id": alert.id,
        "weather_forecast_id": forecast.id,
        "user_id_snapshot": alert.field.user.id,
        "phone_number_snapshot": alert.field.user.phone_number,
        "field_id_snapshot": alert.field.id,
        "field_name_snapshot": alert.field.name,
        "forecast_date_snapshot": forecast.forecast_date,
        "alert_name_snapshot": alert.name,
        "metric_snapshot": alert.metric,
        "operator_snapshot": alert.operator,
        "threshold_value_snapshot": alert.threshold_value,
        "lookahead_days_snapshot": alert.lookahead_days,
        "triggered_value": value,
        "message": build_trigger_message(alert.field.user, alert.field, alert, forecast, value),
        "created_at": now,
        "updated_at": now,
    }


def build_delivery_row(trigger_id: int, target_url: str, next_attempt_at) -> dict:
    now = utcnow()
    return {
        "trigger_id": trigger_id,
        "target_url": target_url,
        "status": DeliveryStatus.PENDING,
        "attempt_count": 0,
        "next_attempt_at": next_attempt_at,
        "last_error": None,
        "response_status": None,
        "sent_at": None,
        "created_at": now,
        "updated_at": now,
    }


def forecast_matches_alert(alert: Alert, forecast: WeatherForecast) -> tuple[bool, int | None]:
    value = get_metric_value(forecast, alert.metric.value)
    return compare_metric(value, alert.operator, alert.threshold_value), value
