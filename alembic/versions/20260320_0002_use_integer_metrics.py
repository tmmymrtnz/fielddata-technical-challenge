"""Use integer metrics and thresholds."""

from alembic import op


revision = "20260320_0002"
down_revision = "20260320_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE weather_forecasts
        ALTER COLUMN temp_min_c TYPE INTEGER USING CAST(ROUND(temp_min_c::numeric) AS INTEGER),
        ALTER COLUMN temp_max_c TYPE INTEGER USING CAST(ROUND(temp_max_c::numeric) AS INTEGER),
        ALTER COLUMN rain_mm TYPE INTEGER USING CAST(ROUND(rain_mm::numeric) AS INTEGER),
        ALTER COLUMN rain_probability_pct TYPE INTEGER USING CAST(ROUND(rain_probability_pct::numeric) AS INTEGER),
        ALTER COLUMN snow_mm TYPE INTEGER USING CAST(ROUND(snow_mm::numeric) AS INTEGER),
        ALTER COLUMN snow_probability_pct TYPE INTEGER USING CAST(ROUND(snow_probability_pct::numeric) AS INTEGER),
        ALTER COLUMN wind_speed_mps TYPE INTEGER USING CAST(ROUND(wind_speed_mps::numeric) AS INTEGER),
        ALTER COLUMN wind_gust_mps TYPE INTEGER USING CAST(ROUND(wind_gust_mps::numeric) AS INTEGER)
        """
    )
    op.execute(
        """
        ALTER TABLE alerts
        ALTER COLUMN threshold_value TYPE INTEGER USING CAST(ROUND(threshold_value::numeric) AS INTEGER)
        """
    )
    op.execute(
        """
        ALTER TABLE alert_triggers
        ALTER COLUMN threshold_value_snapshot TYPE INTEGER USING CAST(ROUND(threshold_value_snapshot::numeric) AS INTEGER),
        ALTER COLUMN triggered_value TYPE INTEGER USING CAST(ROUND(triggered_value::numeric) AS INTEGER)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE weather_forecasts
        ALTER COLUMN temp_min_c TYPE NUMERIC(10, 2) USING temp_min_c::numeric,
        ALTER COLUMN temp_max_c TYPE NUMERIC(10, 2) USING temp_max_c::numeric,
        ALTER COLUMN rain_mm TYPE NUMERIC(10, 2) USING rain_mm::numeric,
        ALTER COLUMN rain_probability_pct TYPE NUMERIC(5, 2) USING rain_probability_pct::numeric,
        ALTER COLUMN snow_mm TYPE NUMERIC(10, 2) USING snow_mm::numeric,
        ALTER COLUMN snow_probability_pct TYPE NUMERIC(5, 2) USING snow_probability_pct::numeric,
        ALTER COLUMN wind_speed_mps TYPE NUMERIC(10, 2) USING wind_speed_mps::numeric,
        ALTER COLUMN wind_gust_mps TYPE NUMERIC(10, 2) USING wind_gust_mps::numeric
        """
    )
    op.execute(
        """
        ALTER TABLE alerts
        ALTER COLUMN threshold_value TYPE NUMERIC(10, 2) USING threshold_value::numeric
        """
    )
    op.execute(
        """
        ALTER TABLE alert_triggers
        ALTER COLUMN threshold_value_snapshot TYPE NUMERIC(10, 2) USING threshold_value_snapshot::numeric,
        ALTER COLUMN triggered_value TYPE NUMERIC(10, 2) USING triggered_value::numeric
        """
    )
