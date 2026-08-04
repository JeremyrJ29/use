from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MessageBus(ABC):
    """Abstract message bus interface."""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def publish(self, subject: str, payload: dict[str, Any]) -> None: ...

    @abstractmethod
    async def subscribe(self, subject: str) -> None: ...
