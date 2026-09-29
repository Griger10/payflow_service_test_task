from uuid import UUID


class ApplicationError(Exception):
    pass


class PaymentNotFoundError(ApplicationError):
    def __init__(self, payment_id: UUID) -> None:
        super().__init__(f"Payment {payment_id} was not found")
        self.payment_id = payment_id


class IdempotencyConflictError(ApplicationError):
    def __init__(self, idempotency_key: str) -> None:
        super().__init__(f"Idempotency key {idempotency_key!r} already exists")
        self.idempotency_key = idempotency_key


class PaymentProcessingFailedError(ApplicationError):
    def __init__(self, payment_id: UUID, cause: Exception) -> None:
        super().__init__(f"Payment {payment_id} was not processed successfully")
        self.payment_id = payment_id
        self.__cause__ = cause
