from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.session import get_session
from app.modules.alerts.models import Alert
from app.modules.alerts.schemas import AlertCreate, AlertRead, AlertUpdate
from app.modules.alerts.service import alert_to_read, require_alert_for_user, require_field_for_user
from app.modules.alerts.validation import AlertThresholdSettings
from app.modules.fields.models import Field

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("", response_model=AlertRead, status_code=status.HTTP_201_CREATED)
async def create_alert(payload: AlertCreate, session: AsyncSession = Depends(get_session)) -> AlertRead:
    field = await require_field_for_user(session, payload.field_id, payload.user_id)

    alert = Alert(
        field_id=field.id,
        name=payload.name,
        metric=payload.metric,
        operator=payload.operator,
        threshold_value=payload.threshold_value,
        lookahead_days=payload.lookahead_days,
        is_active=True,
    )
    session.add(alert)
    await session.commit()

    result = await session.execute(
        select(Alert).options(joinedload(Alert.field)).where(Alert.id == alert.id)
    )
    created_alert = result.scalar_one()
    return AlertRead(**alert_to_read(created_alert))


@router.get("", response_model=list[AlertRead])
async def list_alerts(
    user_id: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_session),
) -> list[AlertRead]:
    result = await session.execute(
        select(Alert)
        .join(Alert.field)
        .options(joinedload(Alert.field))
        .where(Field.user_id == user_id, Alert.deleted_at.is_(None))
        .order_by(Alert.id)
    )
    return [AlertRead(**alert_to_read(alert)) for alert in result.scalars().all()]


@router.get("/{alert_id}", response_model=AlertRead)
async def get_alert(
    alert_id: int,
    user_id: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_session),
) -> AlertRead:
    alert = await require_alert_for_user(session, alert_id, user_id)
    return AlertRead(**alert_to_read(alert))


@router.patch("/{alert_id}", response_model=AlertRead)
async def update_alert(
    alert_id: int,
    payload: AlertUpdate,
    user_id: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_session),
) -> AlertRead:
    alert = await require_alert_for_user(session, alert_id, user_id)
    updates = payload.model_dump(exclude_unset=True)

    for field_name, value in updates.items():
        setattr(alert, field_name, value)

    if alert.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deleted alerts cannot be updated")

    try:
        AlertThresholdSettings(metric=alert.metric, threshold_value=alert.threshold_value)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    alert.last_evaluated_at = None
    await session.commit()

    result = await session.execute(
        select(Alert).options(joinedload(Alert.field)).where(Alert.id == alert.id)
    )
    updated_alert = result.scalar_one()
    return AlertRead(**alert_to_read(updated_alert))


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: int,
    user_id: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_session),
) -> Response:
    alert = await require_alert_for_user(session, alert_id, user_id)
    alert.is_active = False
    from app.db.base import utcnow

    alert.deleted_at = utcnow()
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
