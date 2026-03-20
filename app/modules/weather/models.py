from datetime import date, datetime

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class WeatherForecast(TimestampMixin, Base):
    __tablename__ = "weather_forecasts"
    __table_args__ = (
        UniqueConstraint("field_id", "forecast_date", name="uq_weather_forecasts_field_id_forecast_date"),
        Index("ix_weather_forecasts_field_id_forecast_date", "field_id", "forecast_date"),
        CheckConstraint(
            "rain_probability_pct IS NULL OR (rain_probability_pct >= 0 AND rain_probability_pct <= 100)",
            name="rain_probability_pct_bounds",
        ),
        CheckConstraint(
            "snow_probability_pct IS NULL OR (snow_probability_pct >= 0 AND snow_probability_pct <= 100)",
            name="snow_probability_pct_bounds",
        ),
        CheckConstraint("rain_mm IS NULL OR rain_mm >= 0", name="rain_mm_non_negative"),
        CheckConstraint("snow_mm IS NULL OR snow_mm >= 0", name="snow_mm_non_negative"),
        CheckConstraint("wind_speed_mps IS NULL OR wind_speed_mps >= 0", name="wind_speed_mps_non_negative"),
        CheckConstraint("wind_gust_mps IS NULL OR wind_gust_mps >= 0", name="wind_gust_mps_non_negative"),
        CheckConstraint(
            "temp_min_c IS NULL OR temp_max_c IS NULL OR temp_min_c <= temp_max_c",
            name="temp_min_le_temp_max",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    forecast_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    temp_min_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temp_max_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rain_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rain_probability_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snow_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snow_probability_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wind_speed_mps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wind_gust_mps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    field = relationship("Field", back_populates="forecasts")
    triggers = relationship("AlertTrigger", back_populates="weather_forecast")
