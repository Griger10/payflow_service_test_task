from collections.abc import Callable
from datetime import UTC, datetime

from payflow.domain import Payment
from payflow.domain.enums import PaymentStatus


def test_mark_succeeded_updates_status_and_processed_at(
    payment_factory: Callable[..., Payment],
) -> None:
    payment = payment_factory()
    processed_at = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    payment.mark_succeeded(processed_at)

    assert payment.status == PaymentStatus.SUCCEEDED
    assert payment.processed_at == processed_at


def test_mark_failed_updates_status_and_processed_at(
    payment_factory: Callable[..., Payment],
) -> None:
    payment = payment_factory()
    processed_at = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    payment.mark_failed(processed_at)

    assert payment.status == PaymentStatus.FAILED
    assert payment.processed_at == processed_at
