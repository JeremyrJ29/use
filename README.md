# Universal Semantic Engine (USE)

> A domain-agnostic, self-expanding semantic pipeline that ingests any data source, builds a living semantic graph, and exposes a unified reasoning interface.

![Phase 0](https://img.shields.io/badge/Phase%200-Foundation-blue)

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    USE Pipeline Stages                       │
├─────────────────────────────────────────────────────────────┤
│  1. Multi-Source Ingestion  →  pluggable connectors + NATS  │
│  2. Semantic Lakehouse      →  Raw / Structured / Semantic  │
│     Raw Zone     : MinIO/S3 (blob store)                    │
│     Structured   : PostgreSQL + TimescaleDB                 │
│     Semantic     : MD Layer (Postgres) + Graph (Neo4j)      │
│  3. Metadata & Catalog      →  entity extraction, xref      │
│  4. Dictionary & Ontology   →  versioned, auto-expanding    │
│  5. Semantic Graph Engine   →  factual/inferred/confirmed   │
│  6. Pattern & Anomaly       →  PMI, CUSUM, drift detection  │
│  7. Human-in-the-Loop       →  review queues, approval      │
│  8. Reasoning Interface     →  REST API + optional LLM      │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Start the full stack
docker compose up -d

# Run the API (development)
uv run uvicorn use.main:app --reload
```

API docs available at `http://localhost:8000/docs`

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://use:use_dev@localhost:5432/use` | Postgres async DSN |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j bolt URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `use_dev_neo4j` | Neo4j password |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `NATS_URL` | `nats://localhost:4222` | NATS server URL |
| `MINIO_ENDPOINT` | `localhost:9000` | MinIO endpoint |
| `MINIO_ACCESS_KEY` | `use` | MinIO access key |
| `MINIO_SECRET_KEY` | `use_dev_minio` | MinIO secret key |
| `JWT_SECRET` | *(required)* | JWT signing secret |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_EXPIRY_MINUTES` | `30` | Token expiry in minutes |
| `LOG_LEVEL` | `INFO` | Logging level |
| `ENVIRONMENT` | `development` | Runtime environment |

## Full Technical Spec

See [SPEC.md](./SPEC.md) for the complete USE architecture specification.
