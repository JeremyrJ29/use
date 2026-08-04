"""initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- ingestion_records ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_records (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL,
            raw_payload TEXT NOT NULL,
            encoding TEXT NOT NULL,
            byte_size INTEGER NOT NULL,
            metadata JSONB,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ingestion_records_status ON ingestion_records (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ingestion_records_source_id ON ingestion_records (source_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ingestion_records_metadata_gin ON ingestion_records USING GIN (metadata)")

    # --- lakehouse_records ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS lakehouse_records (
            use_doc_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ingestion_record_id UUID REFERENCES ingestion_records(id),
            source_id TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            version INTEGER NOT NULL DEFAULT 1,
            md_content TEXT,
            md_word_count INTEGER,
            md_tags JSONB,
            md_flags JSONB,
            graph_node_ids JSONB,
            graph_edge_ids JSONB
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_lakehouse_records_md_tags_gin ON lakehouse_records USING GIN (md_tags)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_lakehouse_records_md_flags_gin ON lakehouse_records USING GIN (md_flags)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_lakehouse_records_graph_node_ids_gin ON lakehouse_records USING GIN (graph_node_ids)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_lakehouse_records_graph_edge_ids_gin ON lakehouse_records USING GIN (graph_edge_ids)")

    # --- dict_entries ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS dict_entries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            canonical_id TEXT NOT NULL,
            term TEXT NOT NULL,
            entry_type TEXT NOT NULL,
            aliases JSONB NOT NULL DEFAULT '[]',
            domain TEXT,
            definition TEXT,
            source TEXT NOT NULL,
            confidence FLOAT NOT NULL DEFAULT 0.5,
            review_status TEXT NOT NULL DEFAULT 'pending',
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_dict_entries_canonical_id ON dict_entries (canonical_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_dict_entries_review_status ON dict_entries (review_status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_dict_entries_aliases_gin ON dict_entries USING GIN (aliases)")

    # --- dict_versions ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS dict_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            dict_entry_id UUID REFERENCES dict_entries(id),
            version INTEGER NOT NULL,
            snapshot JSONB NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            reviewer_id TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_dict_versions_snapshot_gin ON dict_versions USING GIN (snapshot)")

    # --- catalog_entries ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS catalog_entries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            canonical_id TEXT UNIQUE NOT NULL,
            entity_type TEXT NOT NULL,
            display_name TEXT NOT NULL,
            aliases JSONB NOT NULL DEFAULT '[]',
            source_ids JSONB NOT NULL DEFAULT '[]',
            document_ids JSONB NOT NULL DEFAULT '[]',
            first_seen TIMESTAMPTZ,
            last_seen TIMESTAMPTZ,
            occurrence_count INTEGER NOT NULL DEFAULT 1,
            confidence FLOAT NOT NULL DEFAULT 0.5,
            confirmed BOOLEAN NOT NULL DEFAULT FALSE,
            notes TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_catalog_entries_canonical_id ON catalog_entries (canonical_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_catalog_entries_aliases_gin ON catalog_entries USING GIN (aliases)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_catalog_entries_source_ids_gin ON catalog_entries USING GIN (source_ids)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_catalog_entries_document_ids_gin ON catalog_entries USING GIN (document_ids)")

    # --- ontology_entries ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS ontology_entries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ontology_type TEXT NOT NULL,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            domain TEXT,
            source TEXT NOT NULL,
            confidence FLOAT NOT NULL DEFAULT 1.0,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # --- review_items ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS review_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            queue TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            payload JSONB NOT NULL,
            reviewer_id TEXT,
            reviewed_at TIMESTAMPTZ,
            notes TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_review_items_queue ON review_items (queue)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_review_items_status ON review_items (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_review_items_payload_gin ON review_items USING GIN (payload)")

    # --- audit_log ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            user_id TEXT,
            payload_hash TEXT,
            detail JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_detail_gin ON audit_log USING GIN (detail)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_entity_id ON audit_log (entity_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS review_items CASCADE")
    op.execute("DROP TABLE IF EXISTS ontology_entries CASCADE")
    op.execute("DROP TABLE IF EXISTS catalog_entries CASCADE")
    op.execute("DROP TABLE IF EXISTS dict_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS dict_entries CASCADE")
    op.execute("DROP TABLE IF EXISTS lakehouse_records CASCADE")
    op.execute("DROP TABLE IF EXISTS ingestion_records CASCADE")
