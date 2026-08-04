# USE — Universal Semantic Engine: Technical Specification

## 1. Purpose

USE is a domain-agnostic, self-expanding semantic pipeline. It ingests arbitrary data sources, builds a living semantic graph, maintains a versioned dictionary and ontology, detects patterns and anomalies, and exposes everything through a unified REST API with optional LLM reasoning.

---

## 2. Architecture Layers

### 2.1 Multi-Source Ingestion Layer

- **Pluggable connectors**: CSV, PDF, JSON, SQL, NoSQL, graph DBs, streams, logs, APIs, plain text
- **Message queue**: NATS (JetStream) as default; Kafka as alternative
- **IngestionRecord**: the unit of raw intake — captures source_id, source_type, raw payload (utf-8 or base64), byte size, metadata, and status
- **Connector base class** provides: `connect()`, `read()`, `disconnect()`, `health_check()`, `list_available()` 

### 2.2 Semantic Lakehouse

Three zones, each with clear promotion criteria:

| Zone | Storage | Content |
|---|---|---|
| Raw | MinIO/S3 | Unprocessed blobs, exactly as received |
| Structured | PostgreSQL + TimescaleDB | Cleaned, parsed, time-indexed records |
| Semantic | MD Layer (Postgres) + Graph Layer (Neo4j) | Meaning-extracted, graph-linked documents |

**MD Layer** (Markdown/Metadata Layer): stores `content`, `word_count`, `tags`, `flags` per document.  
**Graph Layer**: reference set of `node_ids` and `edge_ids` in Neo4j for each document.

**LakehouseRecord** ties an ingestion record to its semantic-zone representation and carries versioning for schema evolution.

### 2.3 Metadata & Catalog Engine

- **Entity extraction**: identifies canonical entities across sources
- **Cross-reference mapping**: links the same entity appearing in multiple documents/sources
- **CatalogEntry**: canonical_id, entity_type, display_name, aliases, source_ids, document_ids, first/last seen, occurrence count, confidence, confirmed flag
- **Confidence scoring**: float 0.0–1.0, updated on each new observation

### 2.4 Self-Expanding Dictionary & Ontology

- **DictEntry**: canonical term, entry_type (entity/abbreviation/unit/vocabulary/value/process_step/concept), aliases, domain, definition, source (human/auto-detected/imported), confidence, review_status, version
- **DictVersion**: full audit trail of every change with reviewer attribution
- **OntologyEntry**: ontology_type, name, description, domain, source, confidence
- **Lookup algorithm**: exact match → fuzzy match → full-text search
- **Auto-detection**: system proposes new terms from corpus; human review approves/rejects
- **Review queue**: all auto-detected entries start in `pending`

### 2.5 Semantic Graph Engine

Three semantic layers in Neo4j:

| Layer | Meaning |
|---|---|
| `factual` | Directly evidenced in source data |
| `inferred` | Derived by pattern/co-occurrence analysis |
| `human_confirmed` | Explicitly approved by a human reviewer |

**GraphNode** types: Entity, Event, Fact, Document, Concept  
**GraphEdge** types: RELATES_TO, PRODUCES, CAUSED, FOLLOWS, CONTRADICTS, LIKELY_RELATES_TO, MISSING_LINK, CONFIRMED_BY, DOCUMENTED_IN

Graph traversal supports configurable depth, layer filtering, and gap/contradiction detection.

### 2.6 Pattern Detection & Anomaly Engine

- **PMI co-occurrence**: Pointwise Mutual Information for term co-occurrence strength
- **Sequence detection**: temporal and logical sequence patterns
- **Drift detection**: CUSUM and ADWIN algorithms for concept/distribution drift
- **AnomalyFlag**: linked to source PatternRecord with severity and acknowledgement status

### 2.7 Human-in-the-Loop Semantic Completion

Review queues for:
- `dict` — proposed new/modified dictionary entries
- `graph` — inferred edges awaiting confirmation
- `anomaly` — detected anomalies requiring human assessment
- `gap` — identified semantic gaps (missing links, unknown entities)
- `ontology` — proposed ontology additions

**ReviewItem**: captures the payload under review, reviewer attribution, decision (approved/rejected), and free-text notes.

### 2.8 Reasoning & Query Interface

- **REST API** (FastAPI): all 40+ routes under `/api/v1`
- **LLM consumer**: optional Ollama integration (default), swappable
- **Async reasoning tasks**: POST /reason returns a task_id; poll status/result
- **Auth**: JWT (HS256), scopes: read / write / review / admin

---

## 3. Data Models (Canonical Schemas)

### IngestionRecord
```
id, source_id, source_type, ingested_at, raw_payload, encoding, byte_size, metadata, status
```

### LakehouseRecord
```
use_doc_id, ingestion_record_id, source_id, created_at, version, md_content, md_word_count, md_tags, md_flags, graph_node_ids, graph_edge_ids
```

### DictEntry
```
id, canonical_id, term, entry_type, aliases, domain, definition, source, confidence, review_status, version, created_at, updated_at
```

### GraphNode
```
id, node_type, canonical_id, properties, created_at
```

### GraphEdge
```
id, from_node_id, to_node_id, edge_type, layer, confidence, properties, created_at
```

### ReviewItem
```
id, queue, status, payload, reviewer_id, reviewed_at, notes, created_at
```

---

## 4. Design Rules

1. **Domain-agnostic**: no hardcoded domain assumptions; all entities are canonical strings with typed metadata
2. **Self-expanding**: the system proposes its own growth; humans approve, not create from scratch
3. **Layered confidence**: every entity, edge, and entry carries a confidence float; nothing is assumed certain
4. **Append-only audit trail**: dict_versions and audit_log are never mutated
5. **Async everywhere**: all I/O is async (SQLAlchemy asyncio, neo4j async, redis-py async, nats-py async)
6. **Queue-first ingestion**: raw data always enters via message queue before persistence
7. **Multi-layer graph**: factual, inferred, and human-confirmed layers are never mixed without explicit filtering

---

## 5. Tech Stack

| Component | Technology |
|---|---|
| API Framework | FastAPI (Python 3.12+) |
| Relational DB | PostgreSQL 16 + TimescaleDB |
| Graph DB | Neo4j 5 |
| Cache | Redis 7 |
| Message Queue | NATS 2 (JetStream) / Kafka |
| Object Store | MinIO (S3-compatible) |
| LLM Consumer | Ollama (optional, swappable) |
| Package Manager | uv |
| ORM | SQLAlchemy 2.0 (asyncio) |
| Migrations | Alembic |
| Auth | python-jose (JWT HS256) |

---

## 6. Deployment

**Edge (single machine):**
```bash
docker compose up -d
uv run uvicorn use.main:app --reload
```

**Cloud (Kubernetes):**
- Each service maps to a Deployment + Service
- TimescaleDB via managed Postgres with pg_timescaledb extension
- Neo4j via Helm chart or managed AuraDB
- MinIO via object storage CSI driver or managed S3

---

*Phase 0 status: Foundation — project scaffold, data models, API skeleton, Docker Compose, migrations, auth*
