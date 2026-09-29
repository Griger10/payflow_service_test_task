from faststream.rabbit import RabbitBroker, RabbitExchange, RabbitQueue

from payflow.infra.messaging.topology import (
    PAYMENTS_DLX,
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_DLQ,
    PAYMENTS_NEW_QUEUE,
    build_payment_retry_queue,
)


async def declare_payments_topology(
    broker: RabbitBroker,
    *,
    retry_max_attempts: int = 3,
    retry_base_delay_seconds: float = 1.0,
) -> None:
    payments_exchange = await broker.declare_exchange(PAYMENTS_EXCHANGE)
    await _declare_and_bind(broker, PAYMENTS_NEW_QUEUE, PAYMENTS_EXCHANGE)
    for attempt in range(1, retry_max_attempts):
        await _declare_and_bind(
            broker,
            build_payment_retry_queue(attempt=attempt, base_delay_seconds=retry_base_delay_seconds),
            PAYMENTS_EXCHANGE,
        )
    dlx_exchange = await broker.declare_exchange(PAYMENTS_DLX)
    dlq = await broker.declare_queue(PAYMENTS_NEW_DLQ)
    await dlq.bind(dlx_exchange, routing_key=PAYMENTS_NEW_DLQ.routing())
    del payments_exchange


async def _declare_and_bind(
    broker: RabbitBroker, queue: RabbitQueue, exchange: RabbitExchange
) -> None:
    declared_exchange = await broker.declare_exchange(exchange)
    declared_queue = await broker.declare_queue(queue)
    await declared_queue.bind(declared_exchange, routing_key=queue.routing())
