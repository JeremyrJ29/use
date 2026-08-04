from __future__ import annotations

from typing import Any

from use.models.dict import DictEntry


class DictService:
    """
    Dictionary lookup service.

    Algorithm: exact match → fuzzy match → full-text search.
    Phase 0: stubs only, returns empty results.
    """

    async def lookup(self, query: str, domain: str | None = None) -> list[DictEntry]:
        """Exact → fuzzy → full-text lookup of a term."""
        return []

    async def exact_match(self, query: str, domain: str | None = None) -> DictEntry | None:
        return None

    async def fuzzy_match(self, query: str, domain: str | None = None) -> list[DictEntry]:
        return []

    async def fulltext_search(self, query: str, domain: str | None = None) -> list[DictEntry]:
        return []

    async def propose_entry(self, term: str, context: dict[str, Any]) -> DictEntry | None:
        """Auto-detection: propose a new dict entry for human review."""
        return None
