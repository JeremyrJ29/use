"""pg_trgm extensions and dict indexes

Revision ID: 003
Revises: 002
Create Date: 2025-01-01 00:00:00.000000
"""
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS fuzzystrmatch")

    # GIN trigram index on dict_entries.term for fuzzy search
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dict_entries_term_trgm "
        "ON dict_entries USING GIN (term gin_trgm_ops)"
    )

    # GIN trigram index on dict_entries.aliases (cast JSONB → text)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dict_entries_aliases_trgm "
        "ON dict_entries USING GIN (aliases::text gin_trgm_ops)"
    )

    # canonical_id index (already in 001, guard with IF NOT EXISTS)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dict_entries_canonical_id_lower "
        "ON dict_entries (lower(canonical_id))"
    )

    # Composite index for review queue queries
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_items_queue_status "
        "ON review_items (queue, status)"
    )

    # Add UNIQUE constraint on dict_entries.canonical_id (needed for ON CONFLICT in import)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_dict_entries_canonical_id'
            ) THEN
                ALTER TABLE dict_entries ADD CONSTRAINT uq_dict_entries_canonical_id UNIQUE (canonical_id);
            END IF;
        END$$
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dict_entries_fts
        ON dict_entries USING GIN (
            to_tsvector('english', term || ' ' || coalesce(definition, ''))
        )
    """)

    # Add dict_entry_id FK column to review_items (for approval propagation)
    op.execute("""
        ALTER TABLE review_items
        ADD COLUMN IF NOT EXISTS dict_entry_id UUID REFERENCES dict_entries(id)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE review_items DROP COLUMN IF EXISTS dict_entry_id")
    op.execute("DROP INDEX IF EXISTS ix_dict_entries_fts")
    op.execute("ALTER TABLE dict_entries DROP CONSTRAINT IF EXISTS uq_dict_entries_canonical_id")
    op.execute("DROP INDEX IF EXISTS ix_review_items_queue_status")
    op.execute("DROP INDEX IF EXISTS ix_dict_entries_canonical_id_lower")
    op.execute("DROP INDEX IF EXISTS ix_dict_entries_aliases_trgm")
    op.execute("DROP INDEX IF EXISTS ix_dict_entries_term_trgm")
    op.execute("DROP EXTENSION IF EXISTS fuzzystrmatch")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
