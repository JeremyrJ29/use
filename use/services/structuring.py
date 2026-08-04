"""
Structuring pipeline — promotes raw IngestionRecords through the
Raw → Structured → Semantic zones of the Semantic Lakehouse.

Flow
----
1.  Write raw payload reference to the Raw Zone (MinIO stub).
2.  Parse raw payload into a structured Python dict.
3.  Extract entities, facts, relationships, timestamps, values.
4.  Resolve extracted entity mentions through DictService.
5.  Select the best-fit schema template.
6.  Build a well-formed MD Layer document (Markdown + YAML frontmatter).
7.  Create Graph Layer stubs (node / edge IDs, wired in Phase 4).
8.  Persist a LakehouseRecord row to Postgres (semantic zone).
9.  Update the ingestion record status to 'complete'.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from use.models.ingestion import IngestionRecord
from use.models.lakehouse import GraphLayerRef, LakehouseRecord, MDLayerContent
from use.services.dict_service import lookup as _dict_lookup, auto_detect_and_queue as _auto_detect
from use.services.schema_templates import SchemaTemplate, select_template

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extraction data-classes
# ---------------------------------------------------------------------------


@dataclass
class EntityMention:
    text: str
    entity_type_hint: str = "UNKNOWN"
    confidence: float = 0.5


@dataclass
class RelMention:
    subject: str
    predicate: str
    object: str


@dataclass
class ValueMention:
    key: str
    value: str
    unit_hint: str = ""


@dataclass
class ExtractionResult:
    entities: list[EntityMention] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    relationships: list[RelMention] = field(default_factory=list)
    timestamps: list[str] = field(default_factory=list)
    values: list[ValueMention] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


@dataclass
class ResolvedExtraction:
    extraction: ExtractionResult
    entity_labels: dict[str, str] = field(default_factory=dict)  # text → CANONICAL_ID or UNKNOWN


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------


async def parse_payload(record: IngestionRecord) -> dict[str, Any]:
    """Parse raw_payload string into a structured Python dict."""
    payload = record.raw_payload

    if record.source_type == "csv":
        try:
            return json.loads(payload)
        except Exception:
            return {"text": payload}

    if record.source_type in ("pdf", "txt", "docx"):
        return {"text": payload}

    if record.source_type == "json":
        try:
            return json.loads(payload)
        except Exception:
            return {"text": payload}

    if record.source_type == "stream":
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except Exception:
            return {"raw": payload}

    # default
    return {"text": payload}


async def extract_semantic_content(
    structured: dict[str, Any],
    source_type: str,
    template: SchemaTemplate,
) -> ExtractionResult:
    """
    Apply simple heuristic extraction rules to the structured payload.
    No ML required in Phase 1.
    """
    result = ExtractionResult()

    entity_keys = {k.lower() for k in template.entity_hints}
    value_keys = {k.lower() for k in template.value_hints}
    ts_keys = {k.lower() for k in template.timestamp_hints}

    for key, val in structured.items():
        key_lc = key.lower()
        str_val = str(val) if val is not None else ""

        # Missing values
        if val is None or str_val.strip() == "":
            result.flags.append(f"[MISSING: {key}]")
            continue

        # Entity hints
        if key_lc in entity_keys:
            result.entities.append(EntityMention(text=str_val, entity_type_hint=key_lc))

        # Value hints
        if key_lc in value_keys:
            result.values.append(ValueMention(key=key, value=str_val))

        # Timestamp hints
        if key_lc in ts_keys:
            result.timestamps.append(str_val)

    # Document type: split text into sentences → first 3 as facts
    if source_type in ("pdf", "txt", "docx", "document"):
        text_body = structured.get("text", "")
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text_body) if s.strip()]
        result.facts.extend(sentences[:3])
        # Treat longer capitalized phrases as entity hints
        for word in re.findall(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", text_body):
            result.entities.append(EntityMention(text=word, entity_type_hint="NAME", confidence=0.3))

    # Tabular / stream: build facts from non-entity non-value fields
    if source_type in ("csv", "tabular", "stream", "sensor_stream"):
        for key, val in structured.items():
            if val is not None and str(val).strip():
                result.facts.append(f"{key}: {val}")

    # Deduplicate entities
    seen: set[str] = set()
    deduped: list[EntityMention] = []
    for e in result.entities:
        if e.text not in seen:
            seen.add(e.text)
            deduped.append(e)
    result.entities = deduped

    return result


async def resolve_entities(
    extraction: ExtractionResult,
    db: AsyncSession | None = None,
    source_id: str = "",
) -> ResolvedExtraction:
    """
    Lookup each entity mention in DictService; flag as [UNKNOWN] when not found.

    When *db* is provided the full lookup algorithm runs and unknown terms are
    queued for human review via auto_detect_and_queue.
    Without *db* (legacy / test path) all entities resolve to UNKNOWN.
    """
    labels: dict[str, str] = {}
    for entity in extraction.entities:
        if db is not None:
            results = await _dict_lookup(
                entity.text, domain=None, db=db
            )
        else:
            results = []

        if results:
            best = results[0]
            if best.confidence >= 0.7:
                labels[entity.text] = best.canonical_id
            elif best.confidence >= 0.5:
                # Ambiguous — keep top-3 candidates for the flag
                top3 = [r.canonical_id for r in results[:3]]
                labels[entity.text] = best.canonical_id
                extraction.flags.append(
                    f"[AMBIGUOUS: {entity.text} | candidates: {', '.join(top3)}]"
                )
                if db is not None:
                    await _auto_detect(
                        entity.text, context=source_id, source_id=source_id, db=db
                    )
            else:
                labels[entity.text] = "UNKNOWN"
                extraction.flags.append(f"[UNKNOWN: {entity.text}]")
                if db is not None:
                    await _auto_detect(
                        entity.text, context=source_id, source_id=source_id, db=db
                    )
        else:
            labels[entity.text] = "UNKNOWN"
            extraction.flags.append(f"[UNKNOWN: {entity.text}]")
            if db is not None:
                await _auto_detect(
                    entity.text, context=source_id, source_id=source_id, db=db
                )

    return ResolvedExtraction(extraction=extraction, entity_labels=labels)


def build_md_document(
    resolved: ResolvedExtraction,
    template: SchemaTemplate,
    record: IngestionRecord,
    doc_id: uuid.UUID,
) -> str:
    """Produce a fully-formed MD Layer document as a Markdown string."""
    ext = resolved.extraction
    now_iso = datetime.now(timezone.utc).isoformat()

    # Derive tags
    tags = [record.source_type, template.name]
    if record.metadata.get("origin"):
        tags.append("ingested")

    flags_list = ext.flags
    tags_yaml = "[" + ", ".join(tags) + "]"
    flags_yaml = "[" + ", ".join(flags_list) + "]" if flags_list else "[]"

    # Summary
    origin = record.metadata.get("origin", record.source_id)
    if record.source_type in ("pdf", "txt", "docx"):
        page = record.metadata.get("page_number", "")
        summary = (
            f"Document ingested from `{origin}`"
            + (f" (page {page})" if page else "")
            + f". Extracted {len(ext.entities)} entities and {len(ext.facts)} facts."
        )
    elif record.source_type == "csv":
        cols = record.metadata.get("columns", [])
        summary = (
            f"Tabular record from `{origin}` with columns: {', '.join(cols[:5])}."
            f" Extracted {len(ext.entities)} entities."
        )
    elif record.source_type == "stream":
        topic = record.metadata.get("topic", record.source_id)
        summary = f"Stream message from topic `{topic}`. Extracted {len(ext.values)} values."
    else:
        summary = (
            f"Record ingested from `{origin}` (type: {record.source_type})."
            f" Extracted {len(ext.entities)} entities."
        )

    lines: list[str] = [
        "---",
        f"use_doc_id: {doc_id}",
        f"source_id: {record.source_id}",
        f"schema: {template.name}",
        f"created_at: {now_iso}",
        "version: 1",
        f"tags: {tags_yaml}",
        f"flags: {flags_yaml}",
        "---",
        "",
        "## Summary",
        summary,
        "",
        "## Entities",
    ]

    if ext.entities:
        for entity in ext.entities:
            canonical = resolved.entity_labels.get(entity.text, "UNKNOWN")
            lines.append(f"- **[{entity.entity_type_hint}]:** {canonical} — {entity.text}")
    else:
        lines.append("- (no entities extracted)")

    lines += ["", "## Facts"]
    if ext.facts:
        for fact in ext.facts:
            lines.append(f"- {fact}")
    else:
        lines.append("- (no facts extracted)")

    lines += ["", "## Relationships"]
    if ext.relationships:
        for rel in ext.relationships:
            lines.append(f"- {rel.subject} → {rel.predicate} → {rel.object}")
    else:
        lines.append("- (none)")

    if ext.values:
        lines += ["", "## Values", "| Key | Value | Unit |", "|-----|-------|------|"]
        for vm in ext.values:
            lines.append(f"| {vm.key} | {vm.value} | {vm.unit_hint or '—'} |")

    if ext.timestamps:
        lines += ["", "## Timestamps"]
        for ts in ext.timestamps:
            lines.append(f"- {ts}")

    if flags_list:
        lines += ["", "## Flags"]
        for flag in flags_list:
            lines.append(f"- {flag}")

    lines += [
        "",
        "## Raw Reference",
        f"Ingestion record: {record.id} | Source: {record.source_id}",
    ]

    return "\n".join(lines)


def build_graph_stubs(resolved: ResolvedExtraction) -> GraphLayerRef:
    """Generate placeholder node/edge IDs for Phase 4 graph wiring."""
    node_ids = [f"node:{uuid.uuid4()}" for _ in resolved.extraction.entities]
    edge_ids = [f"edge:{uuid.uuid4()}" for _ in resolved.extraction.relationships]
    return GraphLayerRef(node_ids=node_ids, edge_ids=edge_ids)


async def write_lakehouse_record(
    record: IngestionRecord,
    md_content: str,
    graph_ref: GraphLayerRef,
    doc_id: uuid.UUID,
    db: AsyncSession,
) -> LakehouseRecord:
    """Insert a row into lakehouse_records."""
    word_count = len(md_content.split())
    # simple tag extraction from frontmatter
    tags: list[str] = []
    flags: list[str] = []
    for line in md_content.splitlines()[:15]:
        if line.startswith("tags:"):
            raw = line.replace("tags:", "").strip().strip("[]")
            tags = [t.strip() for t in raw.split(",") if t.strip()]
        if line.startswith("flags:"):
            raw = line.replace("flags:", "").strip().strip("[]")
            flags = [f.strip() for f in raw.split(",") if f.strip()]

    await db.execute(
        text("""
            INSERT INTO lakehouse_records
                (use_doc_id, ingestion_record_id, source_id, created_at, version,
                 md_content, md_word_count, md_tags, md_flags,
                 graph_node_ids, graph_edge_ids)
            VALUES
                (:doc_id, :ing_id, :src_id, NOW(), 1,
                 :md_content, :wc, :tags, :flags,
                 :node_ids, :edge_ids)
        """),
        {
            "doc_id": str(doc_id),
            "ing_id": str(record.id),
            "src_id": record.source_id,
            "md_content": md_content,
            "wc": word_count,
            "tags": json.dumps(tags),
            "flags": json.dumps(flags),
            "node_ids": json.dumps(graph_ref.node_ids),
            "edge_ids": json.dumps(graph_ref.edge_ids),
        },
    )

    return LakehouseRecord(
        use_doc_id=doc_id,
        ingestion_record_id=record.id,
        source_id=record.source_id,
        md_layer=MDLayerContent(
            content=md_content,
            word_count=word_count,
            tags=tags,
            flags={"flags": flags},
        ),
        graph_layer=graph_ref,
    )


async def update_ingestion_status(
    record_id: uuid.UUID,
    status: str,
    db: AsyncSession,
) -> None:
    """Update the status column of an ingestion_records row."""
    await db.execute(
        text("UPDATE ingestion_records SET status = :status WHERE id = :id"),
        {"status": status, "id": str(record_id)},
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def process(record: IngestionRecord, db: AsyncSession) -> LakehouseRecord:
    """
    Full Raw → Structured → Semantic promotion pipeline.

    Raises on unrecoverable errors; callers should catch and route to DLQ.
    """
    doc_id = uuid.uuid4()
    logger.info("structuring.process: start record=%s doc=%s", record.id, doc_id)

    # Step 1 — Raw Zone (MinIO stub)
    logger.debug("structuring: Raw Zone write stub — MinIO integration deferred to Phase 3")

    # Step 2 — Parse
    structured = await parse_payload(record)

    # Step 3 — Extract
    template = select_template(record)
    extraction = await extract_semantic_content(structured, record.source_type, template)

    # Step 4 — Dict resolution
    resolved = await resolve_entities(extraction, db=db, source_id=record.source_id)

    # Step 5 — Template already selected above

    # Step 6 — Build MD document
    md_content = build_md_document(resolved, template, record, doc_id)

    # Step 7 — Graph stubs
    graph_ref = build_graph_stubs(resolved)

    # Step 8 — Persist lakehouse record
    lakehouse = await write_lakehouse_record(record, md_content, graph_ref, doc_id, db)

    # Step 9 — Update ingestion status
    await update_ingestion_status(record.id, "complete", db)

    logger.info("structuring.process: complete record=%s doc=%s", record.id, doc_id)
    return lakehouse


# ---------------------------------------------------------------------------
# Legacy class shim (keeps existing imports working)
# ---------------------------------------------------------------------------


class StructuringPipeline:
    """
    Thin wrapper around the module-level ``process()`` function.

    Kept for backward compatibility with imports that instantiate
    ``StructuringPipeline`` directly.  New code should call
    ``structuring.process(record, db)`` directly.
    """

    async def raw_to_structured(self, record: IngestionRecord) -> dict | None:
        return await parse_payload(record)

    async def structured_to_semantic(
        self,
        structured: dict,
        record: IngestionRecord,
    ) -> LakehouseRecord | None:
        raise NotImplementedError("Use structuring.process(record, db) instead")

    async def process(self, record: IngestionRecord, db: AsyncSession) -> LakehouseRecord:
        return await process(record, db)

