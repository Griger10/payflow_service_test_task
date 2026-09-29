from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from payflow.domain.enums import Currency, PaymentStatus
from payflow.domain.types import JsonValue


@dataclass(frozen=True, slots=True)
class CreatePaymentCommand:
    amount: Decimal
    currency: Currency
    description: str
    metadata: Mapping[str, JsonValue]
    webhook_url: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class PaymentCreatedResult:
    payment_id: UUID
    status: PaymentStatus
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PaymentDetails:
    payment_id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: Mapping[str, JsonValue]
    status: PaymentStatus
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None
