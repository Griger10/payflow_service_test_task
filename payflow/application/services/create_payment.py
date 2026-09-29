from decimal import Decimal

from payflow.application.dto import CreatePaymentCommand, PaymentCreatedResult
from payflow.application.errors import IdempotencyConflictError
from payflow.application.interfaces import Clock, IdGenerator, UnitOfWorkFactory
from payflow.domain import OutboxEvent, Payment, PaymentStatus


class CreatePayment:
    def __init__(
        self, *, uow_factory: UnitOfWorkFactory, clock: Clock, id_generator: IdGenerator
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._id_generator = id_generator

    async def execute(self, command: CreatePaymentCommand) -> PaymentCreatedResult:
        async with self._uow_factory() as uow:
            existing = await uow.payments.get_by_idempotency_key(command.idempotency_key)
            if existing is not None:
                return self._existing_result(existing, command)

            created_at = self._clock.now()
            payment = Payment(
                id=self._id_generator.new_uuid(),
                amount=command.amount,
                currency=command.currency,
                description=command.description,
                metadata=dict(command.metadata),
                status=PaymentStatus.PENDING,
                idempotency_key=command.idempotency_key,
                webhook_url=command.webhook_url,
                created_at=created_at,
            )
            event = OutboxEvent(
                id=self._id_generator.new_uuid(),
                event_type="payment.created",
                routing_key="payments.new",
                payload={
                    "payment_id": str(payment.id),
                    "idempotency_key": payment.idempotency_key,
                    "created_at": payment.created_at.isoformat(),
                },
                created_at=created_at,
            )

            if await uow.payments.add(payment):
                await uow.outbox.add(event)
                await uow.commit()
                return self._result(payment)
            await uow.rollback()

        return await self._load_concurrent_result(command)

    async def _load_concurrent_result(self, command: CreatePaymentCommand) -> PaymentCreatedResult:
        async with self._uow_factory() as uow:
            existing = await uow.payments.get_by_idempotency_key(command.idempotency_key)
            if existing is None:
                raise IdempotencyConflictError(command.idempotency_key)
            return self._existing_result(existing, command)

    def _existing_result(
        self, payment: Payment, command: CreatePaymentCommand
    ) -> PaymentCreatedResult:
        if not self._same_request(payment, command):
            raise IdempotencyConflictError(command.idempotency_key)
        return self._result(payment)

    @staticmethod
    def _same_request(payment: Payment, command: CreatePaymentCommand) -> bool:
        return (
            _normalized(payment.amount) == _normalized(command.amount)
            and payment.currency == command.currency
            and payment.description == command.description
            and payment.metadata == command.metadata
            and payment.webhook_url == command.webhook_url
        )

    @staticmethod
    def _result(payment: Payment) -> PaymentCreatedResult:
        return PaymentCreatedResult(
            payment_id=payment.id,
            status=payment.status,
            created_at=payment.created_at,
        )


def _normalized(value: Decimal) -> Decimal:
    return value.normalize()
