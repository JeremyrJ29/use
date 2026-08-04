"""add full-text search index on lakehouse_records.md_content

Revision ID: 002
Revises: 001
Create Date: 2024-01-02 00:00:00.000000

Adds a GIN tsvector index to support efficient Postgres full-text search
over MD Layer document content.  Uses a generated tsvector column so the
index stays up-to-date automatically on every INSERT/UPDATE.
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add a generated tsvector column that Postgres maintains automatically.
    op.execute("""
        ALTER TABLE lakehouse_records
            ADD COLUMN IF NOT EXISTS md_content_tsv tsvector
            GENERATED ALWAYS AS
                (to_tsvector('english', COALESCE(md_content, '')))
            STORED
    """)

    # GIN index for fast full-text query matching.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_lakehouse_records_md_content_tsv
        ON lakehouse_records
        USING GIN (md_content_tsv)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_lakehouse_records_md_content_tsv")
    op.execute("ALTER TABLE lakehouse_records DROP COLUMN IF EXISTS md_content_tsv")
