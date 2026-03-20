from __future__ import annotations

from datetime import datetime, date
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class AlertMetric(StrEnum):
    TEMP_MIN_C = "temp_min_c"
    TEMP_MAX_C = "temp_max_c"
    RAIN_MM = "rain_mm"
    RAIN_PROBABILITY_PCT = "rain_probability_pct"
    SNOW_MM = "snow_mm"
    SNOW_PROBABILITY_PCT = "snow_probability_pct"
    WIND_SPEED_MPS = "wind_speed_mps"
    WIND_GUST_MPS = "wind_gust_mps"


class AlertOperator(StrEnum):
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_field_id_active_deleted", "field_id", "is_active", "deleted_at"),
        Index("ix_alerts_active_deleted_id", "is_active", "deleted_at", "id"),
        Index("ix_alerts_active_deleted_last_evaluated_id", "is_active", "deleted_at", "last_evaluated_at", "id"),
        CheckConstraint("lookahead_days BETWEEN 1 AND 30", name="lookahead_days_bounds"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric: Mapped[AlertMetric] = mapped_column(Enum(AlertMetric, native_enum=False), nullable=False)
    operator: Mapped[AlertOperator] = mapped_column(Enum(AlertOperator, native_enum=False), nullable=False)
    threshold_value: Mapped[int] = mapped_column(Integer, nullable=False)
    lookahead_days: Mapped[int] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    field = relationship("Field", back_populates="alerts")
    triggers = relationship("AlertTrigger", back_populates="alert")


class AlertTrigger(TimestampMixin, Base):
    __tablename__ = "alert_triggers"
    __table_args__ = (
        UniqueConstraint("alert_id", "weather_forecast_id", name="uq_alert_triggers_alert_id_weather_forecast_id"),
        Index("ix_alert_triggers_user_id_created_at", "user_id_snapshot", "created_at"),
        Index("ix_alert_triggers_alert_id_created_at", "alert_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False)
    weather_forecast_id: Mapped[int] = mapped_column(ForeignKey("weather_forecasts.id", ondelete="CASCADE"), nullable=False)
    user_id_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    phone_number_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    field_id_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    field_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    forecast_date_snapshot: Mapped[date] = mapped_column(Date, nullable=False)
    alert_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_snapshot: Mapped[AlertMetric] = mapped_column(Enum(AlertMetric, native_enum=False), nullable=False)
    operator_snapshot: Mapped[AlertOperator] = mapped_column(Enum(AlertOperator, native_enum=False), nullable=False)
    threshold_value_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    lookahead_days_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    triggered_value: Mapped[int] = mapped_column(Integer, nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)

    alert = relationship("Alert", back_populates="triggers")
    weather_forecast = relationship("WeatherForecast", back_populates="triggers")
    delivery = relationship("NotificationDelivery", back_populates="trigger", uselist=False)
