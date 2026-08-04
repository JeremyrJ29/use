from __future__ import annotations

import json
from typing import Any

import nats

from use.bus.interface import MessageBus
from use.config import get_settings

settings = get_settings()


class NatsBus(MessageBus):
    """NATS JetStream message bus implementation."""

    def __init__(self) -> None:
        self._nc: nats.aio.client.Client | None = None

    async def connect(self) -> None:
        self._nc = await nats.connect(settings.nats_url)

    async def disconnect(self) -> None:
        if self._nc is not None:
            await self._nc.drain()
            self._nc = None

    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
        if self._nc is None:
            raise RuntimeError("NatsBus not connected")
        data = json.dumps(payload).encode()
        await self._nc.publish(subject, data)

    async def subscribe(self, subject: str) -> None:
        if self._nc is None:
            raise RuntimeError("NatsBus not connected")
        await self._nc.subscribe(subject)
