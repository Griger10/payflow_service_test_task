from types import TracebackType
from typing import override

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payflow.application.interfaces import UnitOfWork
from payflow.infra.database.repositories import (
    SQLAlchemyOutboxRepository,
    SQLAlchemyPaymentRepository,
    SQLAlchemyWebhookDeliveryRepository,
)


class SqlAlchemyUnitOfWork(UnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._committed = False
        self._payments: SQLAlchemyPaymentRepository
        self._outbox: SQLAlchemyOutboxRepository
        self._webhook_deliveries: SQLAlchemyWebhookDeliveryRepository

    @property
    @override
    def payments(self) -> SQLAlchemyPaymentRepository:
        return self._payments

    @property
    @override
    def outbox(self) -> SQLAlchemyOutboxRepository:
        return self._outbox

    @property
    @override
    def webhook_deliveries(self) -> SQLAlchemyWebhookDeliveryRepository:
        return self._webhook_deliveries

    @override
    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        self._committed = False
        self._payments = SQLAlchemyPaymentRepository(self._session)
        self._outbox = SQLAlchemyOutboxRepository(self._session)
        self._webhook_deliveries = SQLAlchemyWebhookDeliveryRepository(self._session)
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self._session is None:
            return
        if not self._committed:
            await self._session.rollback()
        await self._session.close()

    @override
    async def commit(self) -> None:
        if self._session is None:
            msg = "Unit of work is not open"
            raise RuntimeError(msg)
        await self._session.commit()
        self._committed = True

    @override
    async def rollback(self) -> None:
        if self._session is None:
            msg = "Unit of work is not open"
            raise RuntimeError(msg)
        await self._session.rollback()
        self._committed = True
