from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.fields.models import Field
from app.modules.fields.schemas import FieldRead

router = APIRouter(prefix="/fields", tags=["fields"])


@router.get("", response_model=list[FieldRead])
async def list_fields(
    user_id: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_session),
) -> list[FieldRead]:
    result = await session.execute(select(Field).where(Field.user_id == user_id).order_by(Field.id))
    return [FieldRead.model_validate(field) for field in result.scalars().all()]

