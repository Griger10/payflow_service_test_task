from collections.abc import Mapping
from typing import Protocol

from payflow.domain import JsonValue


class PaymentRetryPublisher(Protocol):
    async def publish_retry(self, *, payload: Mapping[str, JsonValue], attempt: int) -> None: ...
