from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ReviewItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    queue: Literal["dict", "graph", "anomaly", "gap", "ontology"]
    status: Literal["pending", "approved", "rejected"] = "pending"
    payload: dict[str, Any]
    reviewer_id: str | None = None
    reviewed_at: datetime | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
