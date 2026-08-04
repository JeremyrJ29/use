"""Ingestion REST endpoints — accept records, enqueue to NATS, report status."""
from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from use.db.postgres import get_db
from use.models.ingestion import IngestionRecord

router = APIRouter()


async def _get_bus():  # noqa: ANN201
    from use.bus.nats_bus import NatsBus

    bus = NatsBus()
    try:
        await bus.connect()
        yield bus
    finally:
        try:
            await bus.disconnect()
        except Exception:
            pass


@router.post("/ingest", status_code=202)
async def ingest_record(
    body: IngestionRecord,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept an IngestionRecord, write it to Postgres, and enqueue it on NATS."""
    await db.execute(
        text("""
            INSERT INTO ingestion_records
                (id, source_id, source_type, ingested_at, raw_payload,
                 encoding, byte_size, metadata, status)
            VALUES
                (:id, :source_id, :source_type, :ingested_at, :raw_payload,
                 :encoding, :byte_size, :metadata, 'pending')
            ON CONFLICT (id) DO NOTHING
        """),
        {
            "id": str(body.id),
            "source_id": body.source_id,
            "source_type": body.source_type,
            "ingested_at": body.ingested_at,
            "raw_payload": body.raw_payload,
            "encoding": body.encoding,
            "byte_size": body.byte_size,
            "metadata": json.dumps(body.metadata),
        },
    )

    # Best-effort NATS publish; failure must not break the HTTP response
    try:
        from use.bus.nats_bus import NatsBus

        bus = NatsBus()
        await bus.connect()
        await bus.publish(
            f"use.ingest.{body.source_type}",
            body.model_dump(mode="json"),
        )
        await bus.disconnect()
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("ingest_record: NATS publish failed: %s", exc)

    return {"record_id": str(body.id), "status": "queued"}


@router.get("/ingest/{record_id}/status")
async def get_ingest_status(
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the current processing status of an ingestion record."""
    row = await db.execute(
        text("SELECT status FROM ingestion_records WHERE id = :id"),
        {"id": str(record_id)},
    )
    result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="Ingestion record not found")
    return {"record_id": str(record_id), "status": result[0]}

