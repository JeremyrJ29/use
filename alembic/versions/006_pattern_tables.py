"""pattern tables

Revision ID: 006
Revises: 005
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- pattern_records ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS pattern_records (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pattern_type VARCHAR(64) NOT NULL,
            entity_ids JSONB NOT NULL,
            score FLOAT NOT NULL,
            support INT NOT NULL DEFAULT 1,
            first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            metadata JSONB DEFAULT '{}',
            CONSTRAINT uq_pattern_type_entities UNIQUE (pattern_type, (entity_ids::text))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pattern_records_type "
        "ON pattern_records (pattern_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pattern_records_entity_ids "
        "ON pattern_records USING GIN (entity_ids)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pattern_records_score "
        "ON pattern_records (score DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pattern_records_last_seen "
        "ON pattern_records (last_seen DESC)"
    )

    # --- anomaly_flags ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS anomaly_flags (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            anomaly_type VARCHAR(64) NOT NULL,
            source_doc_id UUID REFERENCES lakehouse_records(id) ON DELETE SET NULL,
            entity_ids JSONB NOT NULL DEFAULT '[]',
            severity FLOAT NOT NULL DEFAULT 0.5,
            acknowledged BOOL NOT NULL DEFAULT FALSE,
            review_item_id UUID REFERENCES review_items(id) ON DELETE SET NULL,
            detail JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_anomaly_flags_type "
        "ON anomaly_flags (anomaly_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_anomaly_flags_acknowledged "
        "ON anomaly_flags (acknowledged)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_anomaly_flags_severity "
        "ON anomaly_flags (severity DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_anomaly_flags_created_at "
        "ON anomaly_flags (created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS anomaly_flags CASCADE")
    op.execute("DROP TABLE IF EXISTS pattern_records CASCADE")
