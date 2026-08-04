from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    node_type: Literal["Entity", "Event", "Fact", "Document", "Concept"]
    canonical_id: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GraphEdge(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    from_node_id: UUID
    to_node_id: UUID
    edge_type: Literal[
        "RELATES_TO", "PRODUCES", "CAUSED", "FOLLOWS", "CONTRADICTS",
        "LIKELY_RELATES_TO", "MISSING_LINK", "CONFIRMED_BY", "DOCUMENTED_IN"
    ]
    layer: Literal["factual", "inferred", "human_confirmed"]
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
