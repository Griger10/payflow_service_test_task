from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from payflow.domain.enums import Currency
from payflow.presentation.api.schemas import CreatePaymentRequest
from payflow.presentation.consumer.schemas import PaymentCreatedMessage

RETRY_ATTEMPT = 2


def test_create_payment_request_validates_payload_and_default_metadata() -> None:
    request = CreatePaymentRequest.model_validate(
        {
            "amount": "100.00",
            "currency": "RUB",
            "description": "order 42",
            "webhook_url": "https://client.example/webhook",
        },
    )

    assert request.amount == Decimal("100.00")
    assert request.currency == Currency.RUB
    assert request.metadata == {}


def test_create_payment_request_rejects_negative_amount() -> None:
    with pytest.raises(ValidationError):
        CreatePaymentRequest.model_validate(
            {
                "amount": "-1.00",
                "currency": "RUB",
                "description": "order 42",
                "webhook_url": "https://client.example/webhook",
            },
        )


def test_create_payment_request_rejects_unsupported_currency() -> None:
    with pytest.raises(ValidationError):
        CreatePaymentRequest.model_validate(
            {
                "amount": "100.00",
                "currency": "GBP",
                "description": "order 42",
                "webhook_url": "https://client.example/webhook",
            },
        )


def test_payment_created_message_validates_queue_payload() -> None:
    payment_id = uuid4()
    created_at = "2026-08-04T12:00:00+00:00"

    message = PaymentCreatedMessage.model_validate(
        {
            "payment_id": str(payment_id),
            "idempotency_key": "idem-1",
            "created_at": created_at,
        },
    )

    assert message.payment_id == payment_id
    assert message.idempotency_key == "idem-1"
    assert message.created_at == datetime.fromisoformat(created_at)
    assert message.retry_attempt == 0


def test_payment_created_message_keeps_retry_attempt_alias() -> None:
    payment_id = uuid4()

    message = PaymentCreatedMessage.model_validate(
        {
            "payment_id": str(payment_id),
            "idempotency_key": "idem-1",
            "created_at": "2026-08-04T12:00:00+00:00",
            "_retry_attempt": RETRY_ATTEMPT,
        },
    )

    dumped = message.model_dump(mode="json", by_alias=True)

    assert message.retry_attempt == RETRY_ATTEMPT
    assert dumped["_retry_attempt"] == RETRY_ATTEMPT
