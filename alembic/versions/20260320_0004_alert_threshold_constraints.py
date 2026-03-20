"""Add semantic threshold constraints for alerts."""

from alembic import op


revision = "20260320_0004"
down_revision = "20260320_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_alerts_threshold_probability_bounds"),
        "alerts",
        "(metric NOT IN ('RAIN_PROBABILITY_PCT', 'SNOW_PROBABILITY_PCT')) "
        "OR (threshold_value >= 0 AND threshold_value <= 100)",
    )
    op.create_check_constraint(
        op.f("ck_alerts_threshold_non_negative_for_metric"),
        "alerts",
        "(metric NOT IN ('RAIN_MM', 'SNOW_MM', 'WIND_SPEED_MPS', 'WIND_GUST_MPS')) "
        "OR threshold_value >= 0",
    )
    op.create_check_constraint(
        op.f("ck_alert_triggers_threshold_probability_snapshot_bounds"),
        "alert_triggers",
        "(metric_snapshot NOT IN ('RAIN_PROBABILITY_PCT', 'SNOW_PROBABILITY_PCT')) "
        "OR (threshold_value_snapshot >= 0 AND threshold_value_snapshot <= 100)",
    )
    op.create_check_constraint(
        op.f("ck_alert_triggers_threshold_snapshot_non_negative_for_metric"),
        "alert_triggers",
        "(metric_snapshot NOT IN ('RAIN_MM', 'SNOW_MM', 'WIND_SPEED_MPS', 'WIND_GUST_MPS')) "
        "OR threshold_value_snapshot >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_alert_triggers_threshold_snapshot_non_negative_for_metric"), "alert_triggers", type_="check")
    op.drop_constraint(op.f("ck_alert_triggers_threshold_probability_snapshot_bounds"), "alert_triggers", type_="check")
    op.drop_constraint(op.f("ck_alerts_threshold_non_negative_for_metric"), "alerts", type_="check")
    op.drop_constraint(op.f("ck_alerts_threshold_probability_bounds"), "alerts", type_="check")
