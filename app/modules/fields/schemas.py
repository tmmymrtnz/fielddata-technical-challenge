from datetime import datetime

from pydantic import BaseModel


class FieldRead(BaseModel):
    id: int
    user_id: int
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

