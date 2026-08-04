from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MDLayerContent(BaseModel):
    content: str = ""
    word_count: int = 0
    tags: list[str] = Field(default_factory=list)
    flags: dict[str, Any] = Field(default_factory=dict)


class GraphLayerRef(BaseModel):
    node_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)


class LakehouseRecord(BaseModel):
    use_doc_id: UUID = Field(default_factory=uuid4)
    ingestion_record_id: UUID
    source_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = 1
    md_layer: MDLayerContent = Field(default_factory=MDLayerContent)
    graph_layer: GraphLayerRef = Field(default_factory=GraphLayerRef)
