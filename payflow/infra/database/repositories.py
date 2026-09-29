from datetime import datetime
from typing import override
from uuid import UUID

from sqlalchemy import exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.application.interfaces import (
    OutboxRepository,
    PaymentRepository,
    WebhookDeliveryRepository,
)
from payflow.domain import OutboxEvent, Payment
from payflow.domain.enums import OutboxStatus
from payflow.infra.database.models import OutboxModel, PaymentModel, WebhookDeliveryModel


class SQLAlchemyPaymentRepository(PaymentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, payment: Payment) -> bool:
        stmt = (
            insert(PaymentModel)
            .values(
                id=payment.id,
                amount=payment.amount,
                currency=payment.currency,
                description=payment.description,
                metadata_json=payment.metadata,
                status=payment.status,
                idempotency_key=payment.idempotency_key,
                webhook_url=payment.webhook_url,
                created_at=payment.created_at,
                processed_at=payment.processed_at,
            )
            .on_conflict_do_nothing(constraint="uq_payments_idempotency_key")
            .returning(PaymentModel.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    @override
    async def save(self, payment: Payment) -> None:
        stmt = (
            update(PaymentModel)
            .where(PaymentModel.id == payment.id)
            .values(
                amount=payment.amount,
                currency=payment.currency,
                description=payment.description,
                metadata_json=payment.metadata,
                status=payment.status,
                webhook_url=payment.webhook_url,
                processed_at=payment.processed_at,
            )
        )
        await self._session.execute(stmt)

    @override
    async def get_by_id(self, payment_id: UUID, *, for_update: bool = False) -> Payment | None:
        stmt = select(PaymentModel).where(PaymentModel.id == payment_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _payment_from_model(model) if model is not None else None

    @override
    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        stmt = select(PaymentModel).where(PaymentModel.idempotency_key == idempotency_key)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _payment_from_model(model) if model is not None else None


class SQLAlchemyOutboxRepository(OutboxRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, event: OutboxEvent) -> None:
        self._session.add(
            OutboxModel(
                id=event.id,
                event_type=event.event_type,
                routing_key=event.routing_key,
                payload=event.payload,
                status=OutboxStatus.PENDING,
                attempts=event.attempts,
                next_attempt_at=event.created_at,
                created_at=event.created_at,
                last_error=event.last_error,
            )
        )

    @override
    async def claim_ready(
        self, *, limit: int, now: datetime, lease_until: datetime
    ) -> list[OutboxEvent]:
        stmt = (
            select(OutboxModel)
            .where(
                OutboxModel.status == OutboxStatus.PENDING,
                OutboxModel.next_attempt_at <= now,
                or_(OutboxModel.locked_until.is_(None), OutboxModel.locked_until <= now),
            )
            .order_by(OutboxModel.created_at, OutboxModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        if models:
            await self._session.execute(
                update(OutboxModel)
                .where(OutboxModel.id.in_([model.id for model in models]))
                .values(locked_until=lease_until)
            )
        return [_outbox_from_model(model) for model in models]

    @override
    async def mark_published(self, event_id: UUID, *, published_at: datetime) -> None:
        stmt = (
            update(OutboxModel)
            .where(OutboxModel.id == event_id)
            .values(status=OutboxStatus.PUBLISHED, published_at=published_at, locked_until=None)
        )
        await self._session.execute(stmt)

    @override
    async def mark_retry(
        self, event_id: UUID, *, attempts: int, next_attempt_at: datetime, error: str
    ) -> None:
        stmt = (
            update(OutboxModel)
            .where(OutboxModel.id == event_id)
            .values(
                attempts=attempts,
                next_attempt_at=next_attempt_at,
                last_error=error,
                status=OutboxStatus.PENDING,
                locked_until=None,
            )
        )
        await self._session.execute(stmt)

    @override
    async def mark_failed(self, event_id: UUID, *, attempts: int, error: str) -> None:
        stmt = (
            update(OutboxModel)
            .where(OutboxModel.id == event_id)
            .values(
                status=OutboxStatus.FAILED,
                attempts=attempts,
                last_error=error,
                locked_until=None,
            )
        )
        await self._session.execute(stmt)


class SQLAlchemyWebhookDeliveryRepository(WebhookDeliveryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def is_delivered(self, payment_id: UUID) -> bool:
        stmt = select(exists().where(WebhookDeliveryModel.payment_id == payment_id))
        result = await self._session.execute(stmt)
        return bool(result.scalar_one())

    @override
    async def mark_delivered(self, payment_id: UUID, *, delivered_at: datetime) -> bool:
        stmt = (
            insert(WebhookDeliveryModel)
            .values(payment_id=payment_id, delivered_at=delivered_at)
            .on_conflict_do_nothing(index_elements=[WebhookDeliveryModel.payment_id])
            .returning(WebhookDeliveryModel.payment_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None


def _payment_from_model(model: PaymentModel) -> Payment:
    return Payment(
        id=model.id,
        amount=model.amount,
        currency=model.currency,
        description=model.description,
        metadata=dict(model.metadata_json),
        status=model.status,
        idempotency_key=model.idempotency_key,
        webhook_url=model.webhook_url,
        created_at=model.created_at,
        processed_at=model.processed_at,
    )


def _outbox_from_model(model: OutboxModel) -> OutboxEvent:
    return OutboxEvent(
        id=model.id,
        event_type=model.event_type,
        routing_key=model.routing_key,
        payload=dict(model.payload),
        created_at=model.created_at,
        attempts=model.attempts,
        last_error=model.last_error,
    )
