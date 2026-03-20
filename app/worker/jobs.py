from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import case, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from app.core.config import Settings, get_settings
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.modules.alerts.models import Alert, AlertTrigger
from app.modules.alerts.service import (
    build_delivery_row,
    build_trigger_snapshot,
    forecast_matches_alert,
)
from app.modules.fields.models import Field
from app.modules.notifications.delivery import DeliveryResult, deliver_webhook
from app.modules.notifications.models import DeliveryStatus, NotificationDelivery
from app.modules.weather.models import WeatherForecast


@dataclass(slots=True)
class WorkerRunStats:
    evaluated_alerts: int = 0
    created_triggers: int = 0
    delivered_notifications: int = 0
    failed_notifications: int = 0


@dataclass(slots=True)
class ClaimedDelivery:
    delivery_id: int
    trigger_id: int
    target_url: str
    attempt_count: int
    user_id: int
    phone_number: str
    field_name: str
    alert_name: str
    forecast_date: date
    metric: str
    operator: str
    threshold_value: int
    triggered_value: int
    message: str


def _insert_stmt(session: AsyncSession, model, values: dict, index_columns: list[str]):
    dialect_name = session.bind.dialect.name
    if dialect_name == "postgresql":
        insert_fn = pg_insert
    elif dialect_name == "sqlite":
        insert_fn = sqlite_insert
    else:
        raise RuntimeError(f"Unsupported SQL dialect for upsert: {dialect_name}")

    stmt = insert_fn(model).values(**values)
    stmt = stmt.on_conflict_do_nothing(index_elements=index_columns).returning(model.id)
    return stmt


def _backoff_minutes(settings: Settings, attempt_count: int) -> int:
    schedule = settings.parsed_backoff_minutes or [1]
    index = min(max(attempt_count - 1, 0), len(schedule) - 1)
    return schedule[index]


def _supports_skip_locked(session: AsyncSession) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def _alert_claim_cutoff(claimed_at, settings: Settings):
    return claimed_at - timedelta(minutes=max(settings.worker_interval_minutes, 1))


async def _create_trigger_if_missing(session: AsyncSession, alert: Alert, forecast) -> int | None:
    matches, value = forecast_matches_alert(alert, forecast)
    if not matches or value is None:
        return None

    stmt = _insert_stmt(
        session,
        AlertTrigger,
        build_trigger_snapshot(alert, forecast, value),
        ["alert_id", "weather_forecast_id"],
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _create_delivery_if_missing(session: AsyncSession, trigger_id: int, target_url: str) -> int | None:
    stmt = _insert_stmt(
        session,
        NotificationDelivery,
        build_delivery_row(trigger_id, target_url, utcnow()),
        ["trigger_id"],
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _claim_alert_batch_ids(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> list[int]:
    claimed_at = utcnow()
    cutoff = _alert_claim_cutoff(claimed_at, settings)

    async with session_factory() as session:
        stmt = (
            select(Alert.id)
            .where(
                Alert.is_active.is_(True),
                Alert.deleted_at.is_(None),
                or_(Alert.last_evaluated_at.is_(None), Alert.last_evaluated_at <= cutoff),
            )
            .order_by(
                case((Alert.last_evaluated_at.is_(None), 0), else_=1),
                Alert.last_evaluated_at,
                Alert.id,
            )
            .limit(settings.worker_alert_batch_size)
        )
        if _supports_skip_locked(session):
            stmt = stmt.with_for_update(skip_locked=True, of=Alert)

        result = await session.execute(stmt)
        alert_ids = result.scalars().all()
        if not alert_ids:
            return []

        await session.execute(
            update(Alert)
            .where(Alert.id.in_(alert_ids))
            .values(last_evaluated_at=claimed_at)
        )
        await session.commit()

    return list(alert_ids)


async def _load_alert_batch(session: AsyncSession, alert_ids: list[int]) -> list[Alert]:
    result = await session.execute(
        select(Alert)
        .options(joinedload(Alert.field).joinedload(Field.user))
        .where(Alert.id.in_(alert_ids))
        .order_by(Alert.id)
    )
    return result.scalars().unique().all()


async def _load_candidate_forecasts(
    session: AsyncSession,
    alerts: list[Alert],
    today: date,
) -> dict[int, list[WeatherForecast]]:
    if not alerts:
        return {}

    field_ids = sorted({alert.field_id for alert in alerts})
    max_lookahead = max(alert.lookahead_days for alert in alerts)

    result = await session.execute(
        select(WeatherForecast)
        .where(
            WeatherForecast.field_id.in_(field_ids),
            WeatherForecast.forecast_date >= today,
            WeatherForecast.forecast_date < today + timedelta(days=max_lookahead),
        )
        .order_by(WeatherForecast.field_id, WeatherForecast.forecast_date)
    )

    forecasts_by_field: dict[int, list[WeatherForecast]] = defaultdict(list)
    for forecast in result.scalars().all():
        forecasts_by_field[forecast.field_id].append(forecast)
    return forecasts_by_field


async def _evaluate_alert_batch(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    alert_ids: list[int],
    today: date,
) -> WorkerRunStats:
    stats = WorkerRunStats()

    async with session_factory() as session:
        alerts = await _load_alert_batch(session, alert_ids)
        if not alerts:
            return stats

        forecasts_by_field = await _load_candidate_forecasts(session, alerts, today)
        stats.evaluated_alerts = len(alerts)

        for alert in alerts:
            alert_window_end = today + timedelta(days=alert.lookahead_days)
            for forecast in forecasts_by_field.get(alert.field_id, []):
                if forecast.forecast_date >= alert_window_end:
                    break

                trigger_id = await _create_trigger_if_missing(session, alert, forecast)
                if trigger_id is None:
                    continue

                stats.created_triggers += 1
                await _create_delivery_if_missing(session, trigger_id, settings.mock_whatsapp_url)

        await session.commit()

    return stats


async def evaluate_alerts(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> WorkerRunStats:
    stats = WorkerRunStats()
    today = utcnow().date()

    while True:
        alert_ids = await _claim_alert_batch_ids(session_factory, settings)
        if not alert_ids:
            break

        batch_stats = await _evaluate_alert_batch(session_factory, settings, alert_ids, today)
        stats.evaluated_alerts += batch_stats.evaluated_alerts
        stats.created_triggers += batch_stats.created_triggers

    return stats


async def _claim_delivery_batch(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> list[ClaimedDelivery]:
    claimed_at = utcnow()
    lease_until = claimed_at + timedelta(seconds=settings.delivery_claim_ttl_seconds)

    async with session_factory() as session:
        stmt = (
            select(NotificationDelivery)
            .join(NotificationDelivery.trigger)
            .where(
                NotificationDelivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.RETRYING]),
                NotificationDelivery.next_attempt_at <= claimed_at,
            )
            .options(joinedload(NotificationDelivery.trigger))
            .order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
            .limit(settings.worker_delivery_batch_size)
        )
        if _supports_skip_locked(session):
            stmt = stmt.with_for_update(skip_locked=True, of=NotificationDelivery)

        result = await session.execute(stmt)
        deliveries = result.scalars().unique().all()
        if not deliveries:
            return []

        claimed_deliveries: list[ClaimedDelivery] = []
        for delivery in deliveries:
            delivery.next_attempt_at = lease_until
            trigger = delivery.trigger
            claimed_deliveries.append(
                ClaimedDelivery(
                    delivery_id=delivery.id,
                    trigger_id=trigger.id,
                    target_url=delivery.target_url,
                    attempt_count=delivery.attempt_count,
                    user_id=trigger.user_id_snapshot,
                    phone_number=trigger.phone_number_snapshot,
                    field_name=trigger.field_name_snapshot,
                    alert_name=trigger.alert_name_snapshot,
                    forecast_date=trigger.forecast_date_snapshot,
                    metric=trigger.metric_snapshot.value,
                    operator=trigger.operator_snapshot.value,
                    threshold_value=trigger.threshold_value_snapshot,
                    triggered_value=trigger.triggered_value,
                    message=trigger.message,
                )
            )

        await session.commit()

    return claimed_deliveries


def _delivery_payload(delivery: ClaimedDelivery) -> dict:
    return {
        "trigger_id": delivery.trigger_id,
        "attempt_count": delivery.attempt_count + 1,
        "idempotency_key": f"trigger-{delivery.trigger_id}",
        "user_id": delivery.user_id,
        "phone_number": delivery.phone_number,
        "field_name": delivery.field_name,
        "alert_name": delivery.alert_name,
        "forecast_date": delivery.forecast_date.isoformat(),
        "metric": delivery.metric,
        "operator": delivery.operator,
        "threshold_value": delivery.threshold_value,
        "triggered_value": delivery.triggered_value,
        "message": delivery.message,
    }


async def _apply_delivery_outcomes(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    outcomes: list[tuple[ClaimedDelivery, DeliveryResult]],
) -> WorkerRunStats:
    stats = WorkerRunStats()
    if not outcomes:
        return stats

    delivery_ids = [delivery.delivery_id for delivery, _ in outcomes]

    async with session_factory() as session:
        result = await session.execute(
            select(NotificationDelivery).where(NotificationDelivery.id.in_(delivery_ids))
        )
        deliveries = {delivery.id: delivery for delivery in result.scalars().all()}

        for claimed_delivery, outcome in outcomes:
            delivery = deliveries.get(claimed_delivery.delivery_id)
            if delivery is None:
                continue

            delivery.attempt_count += 1
            delivery.response_status = outcome.response_status

            if outcome.success:
                delivery.status = DeliveryStatus.DELIVERED
                delivery.sent_at = utcnow()
                delivery.last_error = None
                delivery.next_attempt_at = utcnow()
                stats.delivered_notifications += 1
                continue

            delivery.last_error = outcome.error_message
            if delivery.attempt_count >= settings.delivery_max_retries:
                delivery.status = DeliveryStatus.FAILED
                stats.failed_notifications += 1
            else:
                delivery.status = DeliveryStatus.RETRYING
                delivery.next_attempt_at = utcnow() + timedelta(
                    minutes=_backoff_minutes(settings, delivery.attempt_count)
                )

        await session.commit()

    return stats


async def deliver_pending_notifications(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> WorkerRunStats:
    stats = WorkerRunStats()

    while True:
        claimed_deliveries = await _claim_delivery_batch(session_factory, settings)
        if not claimed_deliveries:
            break

        outcomes = await asyncio.gather(
            *[
                deliver_webhook(
                    delivery.target_url,
                    _delivery_payload(delivery),
                    settings.request_timeout_seconds,
                )
                for delivery in claimed_deliveries
            ]
        )
        batch_stats = await _apply_delivery_outcomes(
            session_factory,
            settings,
            list(zip(claimed_deliveries, outcomes, strict=True)),
        )
        stats.delivered_notifications += batch_stats.delivered_notifications
        stats.failed_notifications += batch_stats.failed_notifications

    return stats


async def run_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    settings: Settings | None = None,
) -> WorkerRunStats:
    resolved_settings = settings or get_settings()
    eval_stats = await evaluate_alerts(session_factory, resolved_settings)
    delivery_stats = await deliver_pending_notifications(session_factory, resolved_settings)
    return WorkerRunStats(
        evaluated_alerts=eval_stats.evaluated_alerts,
        created_triggers=eval_stats.created_triggers,
        delivered_notifications=delivery_stats.delivered_notifications,
        failed_notifications=delivery_stats.failed_notifications,
    )
