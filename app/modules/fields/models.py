from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Field(TimestampMixin, Base):
    __tablename__ = "fields"
    __table_args__ = (Index("ix_fields_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    user = relationship("User", back_populates="fields")
    forecasts = relationship("WeatherForecast", back_populates="field")
    alerts = relationship("Alert", back_populates="field")

