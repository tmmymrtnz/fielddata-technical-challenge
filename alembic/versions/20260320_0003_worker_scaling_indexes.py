"""Add worker scaling index on alerts."""

import sqlalchemy as sa
from alembic import op


revision = "20260320_0003"
down_revision = "20260320_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("alerts")}
    if "ix_alerts_active_deleted_last_evaluated_id" not in existing_indexes:
        op.create_index(
            "ix_alerts_active_deleted_last_evaluated_id",
            "alerts",
            ["is_active", "deleted_at", "last_evaluated_at", "id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_alerts_active_deleted_last_evaluated_id", table_name="alerts")
