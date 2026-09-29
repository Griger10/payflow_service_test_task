from typing import Final

from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue

PAYMENTS_EXCHANGE_NAME: Final = "payments"
PAYMENTS_DLX_NAME: Final = "payments.dlx"
PAYMENTS_NEW_ROUTING_KEY: Final = "payments.new"
PAYMENTS_NEW_DLQ_ROUTING_KEY: Final = "payments.new.dlq"

PAYMENTS_EXCHANGE: Final = RabbitExchange(
    PAYMENTS_EXCHANGE_NAME, type=ExchangeType.DIRECT, durable=True
)
PAYMENTS_DLX: Final = RabbitExchange(PAYMENTS_DLX_NAME, type=ExchangeType.DIRECT, durable=True)
PAYMENTS_NEW_QUEUE: Final = RabbitQueue(
    PAYMENTS_NEW_ROUTING_KEY,
    routing_key=PAYMENTS_NEW_ROUTING_KEY,
    durable=True,
    arguments={
        "x-dead-letter-exchange": PAYMENTS_DLX_NAME,
        "x-dead-letter-routing-key": PAYMENTS_NEW_DLQ_ROUTING_KEY,
    },
)
PAYMENTS_NEW_DLQ: Final = RabbitQueue(
    PAYMENTS_NEW_DLQ_ROUTING_KEY, routing_key=PAYMENTS_NEW_DLQ_ROUTING_KEY, durable=True
)


def payment_retry_routing_key(attempt: int) -> str:
    return f"{PAYMENTS_NEW_ROUTING_KEY}.retry.{attempt}"


def payment_retry_delay_ms(*, attempt: int, base_delay_seconds: float) -> int:
    delay_seconds = base_delay_seconds * 2 ** (attempt - 1)
    return max(1, int(delay_seconds * 1000))


def build_payment_retry_queue(*, attempt: int, base_delay_seconds: float) -> RabbitQueue:
    return RabbitQueue(
        payment_retry_routing_key(attempt),
        routing_key=payment_retry_routing_key(attempt),
        durable=True,
        arguments={
            "x-message-ttl": payment_retry_delay_ms(
                attempt=attempt, base_delay_seconds=base_delay_seconds
            ),
            "x-dead-letter-exchange": PAYMENTS_EXCHANGE_NAME,
            "x-dead-letter-routing-key": PAYMENTS_NEW_ROUTING_KEY,
        },
    )
