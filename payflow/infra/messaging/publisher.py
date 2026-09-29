from collections.abc import Mapping
from typing import override
from uuid import UUID

from faststream.rabbit import RabbitBroker

from payflow.application.interfaces import EventPublisher
from payflow.domain import JsonValue
from payflow.infra.messaging.topology import PAYMENTS_EXCHANGE


class RabbitEventPublisher(EventPublisher):
    def __init__(self, broker: RabbitBroker) -> None:
        self._broker = broker

    @override
    async def publish(
        self, *, routing_key: str, payload: Mapping[str, JsonValue], message_id: UUID
    ) -> None:
        await self._broker.publish(
            dict(payload),
            exchange=PAYMENTS_EXCHANGE,
            routing_key=routing_key,
            persist=True,
            message_id=str(message_id),
            content_type="application/json",
        )
