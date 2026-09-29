from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from payflow.domain.types import JsonObject


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    id: UUID
    event_type: str
    routing_key: str
    payload: JsonObject
    created_at: datetime
    attempts: int = 0
    last_error: str | None = None
