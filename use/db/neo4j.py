from __future__ import annotations

from collections.abc import AsyncGenerator

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from use.config import get_settings

settings = get_settings()

_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def get_neo4j_session() -> AsyncGenerator[AsyncSession, None]:
    driver = get_driver()
    async with driver.session() as session:
        yield session


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
