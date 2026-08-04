from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class IngestionStatus(BaseModel):
    record_id: UUID
    status: Literal["pending", "processing", "structured", "semantic", "failed"]
    updated_at: datetime


class IngestionRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_id: str
    source_type: Literal[
        "pdf", "docx", "txt", "csv", "sql", "nosql", "graph",
        "stream", "log", "api", "text"
    ]
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    raw_payload: str
    encoding: Literal["utf-8", "base64"] = "utf-8"
    byte_size: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "processing", "structured", "semantic", "failed"] = "pending"
