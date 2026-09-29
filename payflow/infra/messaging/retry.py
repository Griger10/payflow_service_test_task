from collections.abc import Mapping
from typing import override

from faststream.rabbit import RabbitBroker

from payflow.application.interfaces import PaymentRetryPublisher
from payflow.domain import JsonValue
from payflow.infra.messaging.topology import (
    PAYMENTS_EXCHANGE,
    payment_retry_routing_key,
)


class RabbitPaymentRetryPublisher(PaymentRetryPublisher):
    def __init__(self, broker: RabbitBroker) -> None:
        self._broker = broker

    @override
    async def publish_retry(self, *, payload: Mapping[str, JsonValue], attempt: int) -> None:
        retry_payload = dict(payload)
        retry_payload["_retry_attempt"] = attempt
        await self._broker.publish(
            retry_payload,
            exchange=PAYMENTS_EXCHANGE,
            routing_key=payment_retry_routing_key(attempt),
            persist=True,
            content_type="application/json",
        )
