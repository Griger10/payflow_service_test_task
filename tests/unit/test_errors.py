from uuid import UUID

from payflow.application.errors import (
    IdempotencyConflictError,
    PaymentNotFoundError,
    PaymentProcessingFailedError,
)


def test_payment_not_found_error_contains_payment_id() -> None:
    payment_id = UUID("00000000-0000-0000-0000-000000000001")

    error = PaymentNotFoundError(payment_id)

    assert str(payment_id) in str(error)


def test_idempotency_conflict_error_contains_key() -> None:
    error = IdempotencyConflictError("idem-1")

    assert "idem-1" in str(error)


def test_payment_processing_failed_error_keeps_original_cause() -> None:
    payment_id = UUID("00000000-0000-0000-0000-000000000001")
    cause = RuntimeError("gateway timeout")

    error = PaymentProcessingFailedError(payment_id, cause)

    assert str(payment_id) in str(error)
    assert error.__cause__ is cause
