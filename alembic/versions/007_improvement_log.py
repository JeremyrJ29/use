"""improvement_log table

Revision ID: 007
Revises: 006
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS improvement_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            trigger_type VARCHAR(64) NOT NULL,
            trigger_id UUID NOT NULL,
            affected_doc_ids JSONB NOT NULL DEFAULT '[]',
            changes JSONB NOT NULL DEFAULT '{}',
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            error TEXT
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_improvement_log_trigger_type "
        "ON improvement_log (trigger_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_improvement_log_status "
        "ON improvement_log (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_improvement_log_created_at "
        "ON improvement_log (created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS improvement_log CASCADE")
