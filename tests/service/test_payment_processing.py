from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payflow.application.errors import PaymentProcessingFailedError
from payflow.application.services import ProcessPayment
from payflow.domain import Payment
from payflow.infra.database import SqlAlchemyUnitOfWork
from payflow.infra.database.models import PaymentModel
from tests.conftest import FixedClock, FlakyWebhook, SuccessfulGateway

EXPECTED_WEBHOOK_CALLS_AFTER_RETRY = 2


@pytest.mark.asyncio
async def test_processing_retries_webhook_without_charging_gateway_twice(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    payment_factory: Callable[..., Payment],
    payment_processing_service: ProcessPayment,
    successful_gateway: SuccessfulGateway,
    flaky_webhook: FlakyWebhook,
) -> None:
    payment_id = UUID("00000000-0000-0000-0000-000000000001")
    async with uow_factory() as uow:
        await uow.payments.add(payment_factory(payment_id=payment_id))
        await uow.commit()

    with pytest.raises(PaymentProcessingFailedError):
        await payment_processing_service.execute(payment_id)

    await payment_processing_service.execute(payment_id)
    await payment_processing_service.execute(payment_id)

    async with uow_factory() as uow:
        payment = await uow.payments.get_by_id(payment_id)
        webhook_was_delivered = await uow.webhook_deliveries.is_delivered(payment_id)

    assert payment is not None
    assert payment.status.value == "succeeded"
    assert payment.processed_at == datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    assert successful_gateway.calls == 1
    assert flaky_webhook.calls == EXPECTED_WEBHOOK_CALLS_AFTER_RETRY
    assert flaky_webhook.delivery_ids == [payment_id] * EXPECTED_WEBHOOK_CALLS_AFTER_RETRY
    assert webhook_was_delivered is True


@pytest.mark.asyncio
async def test_webhook_is_sent_without_holding_payment_row_lock(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    payment_factory: Callable[..., Payment],
    successful_gateway: SuccessfulGateway,
    fixed_clock: FixedClock,
) -> None:
    payment_id = UUID("00000000-0000-0000-0000-000000000001")
    async with uow_factory() as uow:
        await uow.payments.add(payment_factory(payment_id=payment_id))
        await uow.commit()

    class LockProbeWebhook:
        lock_acquired = False

        async def send(self, url: str, payload: Mapping[str, Any], *, delivery_id: UUID) -> None:
            async with session_factory() as session:
                await session.execute(
                    select(PaymentModel.id)
                    .where(PaymentModel.id == payment_id)
                    .with_for_update(nowait=True)
                )
                self.lock_acquired = True

    webhook = LockProbeWebhook()
    service = ProcessPayment(
        uow_factory=uow_factory,
        payment_gateway=successful_gateway,
        webhook_client=webhook,
        clock=fixed_clock,
    )

    await service.execute(payment_id)

    assert webhook.lock_acquired is True
