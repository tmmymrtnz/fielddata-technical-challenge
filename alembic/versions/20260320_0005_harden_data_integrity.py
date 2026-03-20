"""Harden data integrity constraints."""

import sqlalchemy as sa
from alembic import op


revision = "20260320_0005"
down_revision = "20260320_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("alert_triggers", "message", type_=sa.Text(), existing_type=sa.String(length=500))

    op.create_check_constraint(
        op.f("ck_alerts_deleted_alerts_must_be_inactive"),
        "alerts",
        "deleted_at IS NULL OR is_active = false",
    )
    op.create_check_constraint(
        op.f("ck_alert_triggers_lookahead_days_snapshot_bounds"),
        "alert_triggers",
        "lookahead_days_snapshot BETWEEN 1 AND 30",
    )
    op.create_index(
        "uq_alerts_active_rule",
        "alerts",
        ["field_id", "metric", "operator", "threshold_value", "lookahead_days"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE AND deleted_at IS NULL"),
    )

    op.create_check_constraint(
        op.f("ck_notification_deliveries_response_status_http_bounds"),
        "notification_deliveries",
        "response_status IS NULL OR (response_status >= 100 AND response_status <= 599)",
    )
    op.create_check_constraint(
        op.f("ck_notification_deliveries_attempt_count_matches_status"),
        "notification_deliveries",
        "((status = 'PENDING') AND attempt_count = 0) "
        "OR ((status IN ('RETRYING', 'DELIVERED', 'FAILED')) AND attempt_count > 0)",
    )
    op.create_check_constraint(
        op.f("ck_notification_deliveries_sent_at_matches_status"),
        "notification_deliveries",
        "((status = 'DELIVERED') AND sent_at IS NOT NULL) "
        "OR ((status <> 'DELIVERED') AND sent_at IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_notification_deliveries_delivered_response_status_bounds"),
        "notification_deliveries",
        "(status <> 'DELIVERED') "
        "OR (response_status IS NOT NULL AND response_status >= 200 AND response_status <= 299)",
    )
    op.create_check_constraint(
        op.f("ck_notification_deliveries_delivered_last_error_cleared"),
        "notification_deliveries",
        "(status <> 'DELIVERED') OR last_error IS NULL",
    )
    op.create_check_constraint(
        op.f("ck_notification_deliveries_pending_has_no_delivery_result"),
        "notification_deliveries",
        "(status <> 'PENDING') OR (last_error IS NULL AND response_status IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_notification_deliveries_failed_or_retrying_requires_error"),
        "notification_deliveries",
        "(status NOT IN ('RETRYING', 'FAILED')) OR last_error IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_notification_deliveries_failed_or_retrying_requires_error"),
        "notification_deliveries",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_notification_deliveries_pending_has_no_delivery_result"),
        "notification_deliveries",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_notification_deliveries_delivered_last_error_cleared"),
        "notification_deliveries",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_notification_deliveries_delivered_response_status_bounds"),
        "notification_deliveries",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_notification_deliveries_sent_at_matches_status"),
        "notification_deliveries",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_notification_deliveries_attempt_count_matches_status"),
        "notification_deliveries",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_notification_deliveries_response_status_http_bounds"),
        "notification_deliveries",
        type_="check",
    )

    op.drop_index("uq_alerts_active_rule", table_name="alerts")
    op.drop_constraint(op.f("ck_alert_triggers_lookahead_days_snapshot_bounds"), "alert_triggers", type_="check")
    op.drop_constraint(op.f("ck_alerts_deleted_alerts_must_be_inactive"), "alerts", type_="check")

    op.alter_column("alert_triggers", "message", type_=sa.String(length=500), existing_type=sa.Text())
