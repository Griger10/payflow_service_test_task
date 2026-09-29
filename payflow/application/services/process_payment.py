from uuid import UUID

from payflow.application.errors import PaymentNotFoundError, PaymentProcessingFailedError
from payflow.application.interfaces import (
    Clock,
    PaymentGateway,
    UnitOfWorkFactory,
    WebhookClient,
)
from payflow.domain import JsonObject, Payment
from payflow.domain.enums import PaymentStatus


class ProcessPayment:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        payment_gateway: PaymentGateway,
        webhook_client: WebhookClient,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._payment_gateway = payment_gateway
        self._webhook_client = webhook_client
        self._clock = clock

    async def execute(self, payment_id: UUID) -> None:
        try:
            await self._process_once(payment_id)
        except Exception as exc:
            raise PaymentProcessingFailedError(payment_id, exc) from exc

    async def _process_once(self, payment_id: UUID) -> None:
        payment = await self._settle_payment(payment_id)
        if payment is None:
            return

        # The webhook is sent outside any transaction so a slow receiver never holds a row lock.
        # Concurrent consumers may send it twice; the receiver deduplicates by delivery id.
        await self._webhook_client.send(
            payment.webhook_url, self._build_webhook_payload(payment), delivery_id=payment.id
        )

        async with self._uow_factory() as uow:
            await uow.webhook_deliveries.mark_delivered(payment.id, delivered_at=self._clock.now())
            await uow.commit()

    async def _settle_payment(self, payment_id: UUID) -> Payment | None:
        """Move the payment to a final status; return None if its webhook is already delivered."""
        async with self._uow_factory() as uow:
            payment = await uow.payments.get_by_id(payment_id, for_update=True)
            if payment is None:
                raise PaymentNotFoundError(payment_id)
            if await uow.webhook_deliveries.is_delivered(payment.id):
                return None
            if payment.status == PaymentStatus.PENDING:
                final_status = await self._payment_gateway.process(payment)
                if final_status == PaymentStatus.SUCCEEDED:
                    payment.mark_succeeded(self._clock.now())
                else:
                    payment.mark_failed(self._clock.now())
                await uow.payments.save(payment)
            await uow.commit()
        return payment

    @staticmethod
    def _build_webhook_payload(payment: Payment) -> JsonObject:
        return {
            "payment_id": str(payment.id),
            "status": payment.status.value,
            "amount": str(payment.amount),
            "currency": payment.currency.value,
            "processed_at": payment.processed_at.isoformat() if payment.processed_at else None,
            "metadata": payment.metadata,
        }
