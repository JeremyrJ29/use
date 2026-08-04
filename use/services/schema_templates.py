"""Schema template engine — defines per-source-type document skeletons for the MD Layer."""
from __future__ import annotations

from dataclasses import dataclass, field

from use.models.ingestion import IngestionRecord


@dataclass
class SchemaTemplate:
    """
    Describes the expected shape of an MD Layer document for a given source category.

    Attributes
    ----------
    name               Human-readable template identifier.
    required_sections  Markdown section headings the document must contain.
    required_fields    Top-level metadata fields that must be present.
    entity_hints       Key/column names likely to reference named entities.
    value_hints        Key/column names likely to contain numeric measurements.
    timestamp_hints    Key/column names likely to contain timestamps.
    """

    name: str
    required_sections: list[str] = field(default_factory=list)
    required_fields: list[str] = field(default_factory=list)
    entity_hints: list[str] = field(default_factory=list)
    value_hints: list[str] = field(default_factory=list)
    timestamp_hints: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, SchemaTemplate] = {
    "generic": SchemaTemplate(
        name="generic",
        required_sections=["Summary", "Entities", "Facts", "Flags", "Raw Reference"],
        required_fields=["use_doc_id", "source_id", "created_at"],
        entity_hints=["name", "id", "entity", "subject", "object", "title"],
        value_hints=["value", "amount", "count", "total", "score"],
        timestamp_hints=["timestamp", "date", "time", "created_at", "updated_at"],
    ),
    "document": SchemaTemplate(
        name="document",
        required_sections=["Summary", "Entities", "Facts", "Relationships", "Flags", "Raw Reference"],
        required_fields=["use_doc_id", "source_id", "created_at"],
        entity_hints=["person", "organization", "location", "product", "name", "author", "title"],
        value_hints=["number", "amount", "percentage", "quantity"],
        timestamp_hints=["date", "time", "published", "created", "updated"],
    ),
    "tabular": SchemaTemplate(
        name="tabular",
        required_sections=["Summary", "Entities", "Records", "Anomalies", "Flags", "Raw Reference"],
        required_fields=["use_doc_id", "source_id", "created_at"],
        entity_hints=["id", "name", "key", "label", "category", "type", "code"],
        value_hints=["value", "amount", "count", "total", "price", "rate", "score", "quantity"],
        timestamp_hints=["date", "time", "timestamp", "created_at", "updated_at", "datetime"],
    ),
    "event_log": SchemaTemplate(
        name="event_log",
        required_sections=["Summary", "Entities", "Events", "Anomalies", "Flags", "Raw Reference"],
        required_fields=["use_doc_id", "source_id", "created_at"],
        entity_hints=["host", "user", "service", "source", "target", "process", "pid"],
        value_hints=["level", "status", "code", "duration", "count"],
        timestamp_hints=["timestamp", "time", "datetime", "logged_at", "@timestamp"],
    ),
    "sensor_stream": SchemaTemplate(
        name="sensor_stream",
        required_sections=["Summary", "Entity", "Measurements", "Anomalies", "Flags", "Raw Reference"],
        required_fields=["use_doc_id", "source_id", "created_at"],
        entity_hints=["device_id", "sensor_id", "unit_id", "node", "asset", "equipment"],
        value_hints=["temperature", "humidity", "pressure", "voltage", "current", "value", "reading"],
        timestamp_hints=["timestamp", "time", "ts", "measured_at", "reported_at"],
    ),
}


# ---------------------------------------------------------------------------
# Template selection
# ---------------------------------------------------------------------------

_SOURCE_TYPE_MAP: dict[str, str] = {
    "pdf": "document",
    "docx": "document",
    "txt": "document",
    "csv": "tabular",
    "log": "event_log",
    "stream": "sensor_stream",
}


def select_template(record: IngestionRecord) -> SchemaTemplate:
    """
    Return the best-fit SchemaTemplate for *record*.

    Mapping:
      pdf / docx / txt → document
      csv              → tabular
      log              → event_log
      stream           → sensor_stream
      everything else  → generic
    """
    template_name = _SOURCE_TYPE_MAP.get(record.source_type, "generic")
    return TEMPLATES[template_name]
