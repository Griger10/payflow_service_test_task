from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from payflow.domain import JsonValue


class WebhookClient(Protocol):
    async def send(self, url: str, payload: Mapping[str, JsonValue], *, delivery_id: UUID) -> None:
        pass
