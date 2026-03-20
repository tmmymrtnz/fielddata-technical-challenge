"""Initial schema."""

from alembic import op
import sqlalchemy as sa


revision = "20260320_0001"
down_revision = None
branch_labels = None
depends_on = None


alert_metric_enum = sa.Enum(
    "temp_min_c",
    "temp_max_c",
    "rain_mm",
    "rain_probability_pct",
    "snow_mm",
    "snow_probability_pct",
    "wind_speed_mps",
    "wind_gust_mps",
    name="alertmetric",
    native_enum=False,
)

alert_operator_enum = sa.Enum("lt", "lte", "gt", "gte", name="alertoperator", native_enum=False)
delivery_status_enum = sa.Enum("pending", "retrying", "delivered", "failed", name="deliverystatus", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )

    op.create_table(
        "fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_fields_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fields")),
    )
    op.create_index("ix_fields_user_id", "fields", ["user_id"], unique=False)

    op.create_table(
        "weather_forecasts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("field_id", sa.Integer(), nullable=False),
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("temp_min_c", sa.Integer(), nullable=True),
        sa.Column("temp_max_c", sa.Integer(), nullable=True),
        sa.Column("rain_mm", sa.Integer(), nullable=True),
        sa.Column("rain_probability_pct", sa.Integer(), nullable=True),
        sa.Column("snow_mm", sa.Integer(), nullable=True),
        sa.Column("snow_probability_pct", sa.Integer(), nullable=True),
        sa.Column("wind_speed_mps", sa.Integer(), nullable=True),
        sa.Column("wind_gust_mps", sa.Integer(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rain_probability_pct IS NULL OR (rain_probability_pct >= 0 AND rain_probability_pct <= 100)",
            name=op.f("ck_weather_forecasts_rain_probability_pct_bounds"),
        ),
        sa.CheckConstraint("rain_mm IS NULL OR rain_mm >= 0", name=op.f("ck_weather_forecasts_rain_mm_non_negative")),
        sa.CheckConstraint("snow_mm IS NULL OR snow_mm >= 0", name=op.f("ck_weather_forecasts_snow_mm_non_negative")),
        sa.CheckConstraint(
            "snow_probability_pct IS NULL OR (snow_probability_pct >= 0 AND snow_probability_pct <= 100)",
            name=op.f("ck_weather_forecasts_snow_probability_pct_bounds"),
        ),
        sa.CheckConstraint(
            "temp_min_c IS NULL OR temp_max_c IS NULL OR temp_min_c <= temp_max_c",
            name=op.f("ck_weather_forecasts_temp_min_le_temp_max"),
        ),
        sa.CheckConstraint(
            "wind_gust_mps IS NULL OR wind_gust_mps >= 0",
            name=op.f("ck_weather_forecasts_wind_gust_mps_non_negative"),
        ),
        sa.CheckConstraint(
            "wind_speed_mps IS NULL OR wind_speed_mps >= 0",
            name=op.f("ck_weather_forecasts_wind_speed_mps_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["field_id"],
            ["fields.id"],
            name=op.f("fk_weather_forecasts_field_id_fields"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weather_forecasts")),
        sa.UniqueConstraint("field_id", "forecast_date", name="uq_weather_forecasts_field_id_forecast_date"),
    )
    op.create_index("ix_weather_forecasts_field_id_forecast_date", "weather_forecasts", ["field_id", "forecast_date"], unique=False)

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("field_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("metric", alert_metric_enum, nullable=False),
        sa.Column("operator", alert_operator_enum, nullable=False),
        sa.Column("threshold_value", sa.Integer(), nullable=False),
        sa.Column("lookahead_days", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("lookahead_days BETWEEN 1 AND 30", name=op.f("ck_alerts_lookahead_days_bounds")),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name=op.f("fk_alerts_field_id_fields"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index("ix_alerts_field_id_active_deleted", "alerts", ["field_id", "is_active", "deleted_at"], unique=False)
    op.create_index("ix_alerts_active_deleted_id", "alerts", ["is_active", "deleted_at", "id"], unique=False)
    op.create_index(
        "ix_alerts_active_deleted_last_evaluated_id",
        "alerts",
        ["is_active", "deleted_at", "last_evaluated_at", "id"],
        unique=False,
    )

    op.create_table(
        "alert_triggers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alert_id", sa.Integer(), nullable=False),
        sa.Column("weather_forecast_id", sa.Integer(), nullable=False),
        sa.Column("user_id_snapshot", sa.Integer(), nullable=False),
        sa.Column("phone_number_snapshot", sa.String(length=32), nullable=False),
        sa.Column("field_id_snapshot", sa.Integer(), nullable=False),
        sa.Column("field_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("forecast_date_snapshot", sa.Date(), nullable=False),
        sa.Column("alert_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("metric_snapshot", alert_metric_enum, nullable=False),
        sa.Column("operator_snapshot", alert_operator_enum, nullable=False),
        sa.Column("threshold_value_snapshot", sa.Integer(), nullable=False),
        sa.Column("lookahead_days_snapshot", sa.Integer(), nullable=False),
        sa.Column("triggered_value", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], name=op.f("fk_alert_triggers_alert_id_alerts"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["weather_forecast_id"],
            ["weather_forecasts.id"],
            name=op.f("fk_alert_triggers_weather_forecast_id_weather_forecasts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_triggers")),
        sa.UniqueConstraint("alert_id", "weather_forecast_id", name="uq_alert_triggers_alert_id_weather_forecast_id"),
    )
    op.create_index("ix_alert_triggers_user_id_created_at", "alert_triggers", ["user_id_snapshot", "created_at"], unique=False)
    op.create_index("ix_alert_triggers_alert_id_created_at", "alert_triggers", ["alert_id", "created_at"], unique=False)

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trigger_id", sa.Integer(), nullable=False),
        sa.Column("target_url", sa.String(length=500), nullable=False),
        sa.Column("status", delivery_status_enum, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name=op.f("ck_notification_deliveries_attempt_count_non_negative")),
        sa.ForeignKeyConstraint(
            ["trigger_id"],
            ["alert_triggers.id"],
            name=op.f("fk_notification_deliveries_trigger_id_alert_triggers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
        sa.UniqueConstraint("trigger_id", name=op.f("uq_notification_deliveries_trigger_id")),
    )
    op.create_index(
        "ix_notification_deliveries_status_next_attempt_at",
        "notification_deliveries",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notification_deliveries_status_next_attempt_at", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_index("ix_alert_triggers_alert_id_created_at", table_name="alert_triggers")
    op.drop_index("ix_alert_triggers_user_id_created_at", table_name="alert_triggers")
    op.drop_table("alert_triggers")
    op.drop_index("ix_alerts_active_deleted_last_evaluated_id", table_name="alerts")
    op.drop_index("ix_alerts_active_deleted_id", table_name="alerts")
    op.drop_index("ix_alerts_field_id_active_deleted", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_weather_forecasts_field_id_forecast_date", table_name="weather_forecasts")
    op.drop_table("weather_forecasts")
    op.drop_index("ix_fields_user_id", table_name="fields")
    op.drop_table("fields")
    op.drop_table("users")
