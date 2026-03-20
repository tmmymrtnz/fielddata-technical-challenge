from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.session import get_session
from app.modules.alerts.models import AlertTrigger
from app.modules.notifications.schemas import NotificationDeliveryRead, NotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
async def list_notifications(
    user_id: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_session),
) -> list[NotificationRead]:
    result = await session.execute(
        select(AlertTrigger)
        .where(AlertTrigger.user_id_snapshot == user_id)
        .options(
            joinedload(AlertTrigger.delivery),
        )
        .order_by(AlertTrigger.created_at.desc())
    )

    notifications: list[NotificationRead] = []
    for trigger in result.scalars().all():
        delivery = None
        if trigger.delivery is not None:
            delivery = NotificationDeliveryRead(
                status=trigger.delivery.status,
                attempt_count=trigger.delivery.attempt_count,
                response_status=trigger.delivery.response_status,
                last_error=trigger.delivery.last_error,
                sent_at=trigger.delivery.sent_at,
                next_attempt_at=trigger.delivery.next_attempt_at,
            )
        notifications.append(
            NotificationRead(
                trigger_id=trigger.id,
                alert_id=trigger.alert_id,
                alert_name=trigger.alert_name_snapshot,
                user_id=trigger.user_id_snapshot,
                field_id=trigger.field_id_snapshot,
                field_name=trigger.field_name_snapshot,
                forecast_date=trigger.forecast_date_snapshot,
                metric=trigger.metric_snapshot,
                operator=trigger.operator_snapshot,
                threshold_value=trigger.threshold_value_snapshot,
                triggered_value=trigger.triggered_value,
                message=trigger.message,
                created_at=trigger.created_at,
                delivery=delivery,
            )
        )
    return notifications
