from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from payflow.infra.config import ServiceConfig
from payflow.infra.database import build_engine, build_session_factory


@dataclass(frozen=True, slots=True)
class Resources:
    """Long-lived objects owned by a process for its whole lifetime."""

    settings: ServiceConfig
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


@asynccontextmanager
async def open_resources(settings: ServiceConfig | None = None) -> AsyncIterator[Resources]:
    settings = settings or ServiceConfig()
    engine = build_engine(settings.database)
    try:
        yield Resources(
            settings=settings,
            engine=engine,
            session_factory=build_session_factory(engine),
        )
    finally:
        await engine.dispose()
