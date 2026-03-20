"""Add worker scaling index on alerts."""

from alembic import op


revision = "20260320_0003"
down_revision = "20260320_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_alerts_active_deleted_last_evaluated_id",
        "alerts",
        ["is_active", "deleted_at", "last_evaluated_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_active_deleted_last_evaluated_id", table_name="alerts")
