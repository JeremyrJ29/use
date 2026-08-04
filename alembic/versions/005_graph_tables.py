"""graph tables

Revision ID: 005
Revises: 003
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op

revision = "005"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- graph_nodes ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS graph_nodes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            node_type TEXT NOT NULL,
            canonical_id TEXT,
            properties JSONB NOT NULL DEFAULT '{}',
            source_doc_id UUID,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_graph_nodes_type_canonical "
        "ON graph_nodes (node_type, canonical_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_graph_nodes_source_doc "
        "ON graph_nodes (source_doc_id)"
    )

    # --- graph_edges ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS graph_edges (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            from_node_id UUID NOT NULL REFERENCES graph_nodes(id),
            to_node_id UUID NOT NULL REFERENCES graph_nodes(id),
            edge_type TEXT NOT NULL,
            layer TEXT NOT NULL DEFAULT 'factual',
            confidence FLOAT NOT NULL DEFAULT 1.0,
            properties JSONB NOT NULL DEFAULT '{}',
            source_doc_id UUID,
            acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_graph_edges_from_type "
        "ON graph_edges (from_node_id, edge_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_graph_edges_to_type "
        "ON graph_edges (to_node_id, edge_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_graph_edges_layer_type "
        "ON graph_edges (layer, edge_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_graph_edges_acknowledged "
        "ON graph_edges (acknowledged) "
        "WHERE edge_type IN ('MISSING_LINK','CONTRADICTS')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS graph_edges CASCADE")
    op.execute("DROP TABLE IF EXISTS graph_nodes CASCADE")
