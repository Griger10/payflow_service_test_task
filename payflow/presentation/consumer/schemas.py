from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PaymentCreatedMessage(BaseModel):
    payment_id: UUID
    idempotency_key: str
    created_at: datetime
    retry_attempt: int = Field(
        default=0,
        ge=0,
        validation_alias="_retry_attempt",
        serialization_alias="_retry_attempt",
    )
