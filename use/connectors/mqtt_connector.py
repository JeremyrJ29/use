"""MQTT connector — subscribes to one or more topics and streams messages as IngestionRecords."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

from use.connectors.base import Connector
from use.models.ingestion import IngestionRecord

logger = logging.getLogger(__name__)

MessageCallback = Callable[[IngestionRecord], Awaitable[None]]


class MQTTConnector(Connector):
    """
    Streaming connector that subscribes to MQTT broker topics via *aiomqtt*.

    Each received message is converted to an IngestionRecord with
    ``source_type='stream'`` and delivered to the registered callback.

    Config
    ------
    broker_host : str         MQTT broker hostname or IP.
    broker_port : int         Broker port (default 1883).
    topics      : list[str]   Topics to subscribe to.
    client_id   : str         MQTT client identifier.
    """

    source_type = "stream"

    def __init__(
        self,
        broker_host: str,
        topics: list[str],
        client_id: str,
        broker_port: int = 1883,
    ) -> None:
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topics = topics
        self.client_id = client_id
        self._client: Any = None

    async def connect(self) -> None:
        """No persistent connection needed; aiomqtt handles context per subscribe call."""
        pass

    async def disconnect(self) -> None:
        pass

    async def health_check(self) -> bool:
        """Attempt a brief TCP connection to the broker to verify reachability."""
        import asyncio
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.broker_host, self.broker_port),
                timeout=3.0,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    async def read(self) -> list[dict[str, Any]]:
        """Not applicable for streaming connectors — use subscribe() instead."""
        return []

    async def subscribe(self, callback: MessageCallback, stop_after: int | None = None) -> None:
        """
        Connect to the broker, subscribe to all configured topics, and call
        *callback* for every received message.

        Parameters
        ----------
        callback    : async callable that receives an IngestionRecord.
        stop_after  : if set, stop after this many messages (useful for testing).
        """
        import aiomqtt  # type: ignore[import-untyped]

        received = 0
        try:
            async with aiomqtt.Client(
                hostname=self.broker_host,
                port=self.broker_port,
                identifier=self.client_id,
            ) as client:
                for topic in self.topics:
                    await client.subscribe(topic)
                logger.info(
                    "MQTTConnector: subscribed to %s on %s:%d",
                    self.topics,
                    self.broker_host,
                    self.broker_port,
                )
                async for message in client.messages:
                    try:
                        payload_str = message.payload.decode("utf-8")  # type: ignore[union-attr]
                    except Exception:
                        payload_str = repr(message.payload)

                    record = IngestionRecord(
                        id=uuid4(),
                        source_id=str(message.topic),
                        source_type="stream",
                        ingested_at=datetime.utcnow(),
                        raw_payload=payload_str,
                        encoding="utf-8",
                        byte_size=len(payload_str.encode()),
                        metadata={
                            "topic": str(message.topic),
                            "qos": message.qos,
                            "broker_host": self.broker_host,
                        },
                    )
                    try:
                        await callback(record)
                    except Exception as exc:
                        logger.error("MQTTConnector callback error: %s", exc)

                    received += 1
                    if stop_after is not None and received >= stop_after:
                        break
        except Exception as exc:
            logger.error("MQTTConnector.subscribe error: %s", exc)
            raise
