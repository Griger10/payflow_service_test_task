from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from payflow.domain import JsonValue


class EventPublisher(Protocol):
    async def publish(
        self, *, routing_key: str, payload: Mapping[str, JsonValue], message_id: UUID
    ) -> None:
        pass
