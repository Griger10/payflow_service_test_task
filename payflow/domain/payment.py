from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from payflow.domain.enums import Currency, PaymentStatus
from payflow.domain.types import JsonObject


@dataclass(slots=True)
class Payment:
    id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: JsonObject
    status: PaymentStatus
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None = None

    def mark_succeeded(self, processed_at: datetime) -> None:
        self.status = PaymentStatus.SUCCEEDED
        self.processed_at = processed_at

    def mark_failed(self, processed_at: datetime) -> None:
        self.status = PaymentStatus.FAILED
        self.processed_at = processed_at
