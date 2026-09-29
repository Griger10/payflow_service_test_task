from uuid import UUID

from payflow.application.dto import PaymentDetails
from payflow.application.errors import PaymentNotFoundError
from payflow.application.interfaces import UnitOfWorkFactory
from payflow.domain import Payment


class GetPayment:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, payment_id: UUID) -> PaymentDetails:
        async with self._uow_factory() as uow:
            payment = await uow.payments.get_by_id(payment_id)
            if payment is None:
                raise PaymentNotFoundError(payment_id)
            return self._to_details(payment)

    @staticmethod
    def _to_details(payment: Payment) -> PaymentDetails:
        return PaymentDetails(
            payment_id=payment.id,
            amount=payment.amount,
            currency=payment.currency,
            description=payment.description,
            metadata=payment.metadata,
            status=payment.status,
            idempotency_key=payment.idempotency_key,
            webhook_url=payment.webhook_url,
            created_at=payment.created_at,
            processed_at=payment.processed_at,
        )
