from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from payflow.domain import OutboxEvent, Payment


class PaymentRepository(Protocol):
    async def add(self, payment: Payment) -> bool:
        pass

    async def save(self, payment: Payment) -> None:
        pass

    async def get_by_id(self, payment_id: UUID, *, for_update: bool = False) -> Payment | None:
        pass

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        pass


class OutboxRepository(Protocol):
    async def add(self, event: OutboxEvent) -> None:
        pass

    async def claim_ready(
        self, *, limit: int, now: datetime, lease_until: datetime
    ) -> list[OutboxEvent]:
        pass

    async def mark_published(self, event_id: UUID, *, published_at: datetime) -> None:
        pass

    async def mark_retry(
        self, event_id: UUID, *, attempts: int, next_attempt_at: datetime, error: str
    ) -> None:
        pass

    async def mark_failed(self, event_id: UUID, *, attempts: int, error: str) -> None:
        pass


class WebhookDeliveryRepository(Protocol):
    async def is_delivered(self, payment_id: UUID) -> bool:
        pass

    async def mark_delivered(self, payment_id: UUID, *, delivered_at: datetime) -> bool:
        pass


class UnitOfWork(Protocol):
    @property
    def payments(self) -> PaymentRepository:
        pass

    @property
    def outbox(self) -> OutboxRepository:
        pass

    @property
    def webhook_deliveries(self) -> WebhookDeliveryRepository:
        pass

    async def __aenter__(self) -> Self:
        pass

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork:
        pass
