"""catalog indexes for Phase 3

Revision ID: 004
Revises: 003
Create Date: 2024-01-04 00:00:00.000000
"""
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Trigram index on display_name for fast ILIKE / similarity search.
    # pg_trgm extension was enabled in migration 003.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_catalog_entries_display_name_trgm
        ON catalog_entries USING GIN (display_name gin_trgm_ops)
    """)

    # Entity-type filter index
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_catalog_entries_entity_type
        ON catalog_entries (entity_type)
    """)

    # Confirmed flag filter index
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_catalog_entries_confirmed
        ON catalog_entries (confirmed)
    """)

    # Descending occurrence_count for "most observed" sorting
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_catalog_entries_occurrence_count_desc
        ON catalog_entries (occurrence_count DESC)
    """)

    # GIN indexes on JSONB arrays (aliases / document_ids already created in
    # migration 001 under different names; we add the canonical names here so
    # queries have the right stats — IF NOT EXISTS keeps it idempotent).
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_catalog_entries_aliases_gin
        ON catalog_entries USING GIN (aliases)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_catalog_entries_document_ids_gin
        ON catalog_entries USING GIN (document_ids)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_catalog_entries_document_ids_gin")
    op.execute("DROP INDEX IF EXISTS ix_catalog_entries_aliases_gin")
    op.execute("DROP INDEX IF EXISTS ix_catalog_entries_occurrence_count_desc")
    op.execute("DROP INDEX IF EXISTS ix_catalog_entries_confirmed")
    op.execute("DROP INDEX IF EXISTS ix_catalog_entries_entity_type")
    op.execute("DROP INDEX IF EXISTS ix_catalog_entries_display_name_trgm")
