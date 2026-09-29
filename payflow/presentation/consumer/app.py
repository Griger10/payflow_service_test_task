import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from faststream import AckPolicy, ContextRepo, FastStream
from faststream.rabbit import RabbitBroker, RabbitMessage
from pydantic import ValidationError

from payflow.application.errors import PaymentProcessingFailedError
from payflow.bootstrap.resources import open_resources
from payflow.infra.config import ServiceConfig
from payflow.infra.messaging.declaration import declare_payments_topology
from payflow.infra.messaging.topology import (
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_DLQ,
    PAYMENTS_NEW_QUEUE,
    payment_retry_delay_ms,
)
from payflow.presentation.consumer.dependencies import (
    BROKER_KEY,
    HTTP_CLIENT_KEY,
    RESOURCES_KEY,
    ProcessPaymentDep,
    RetryPublisherDep,
    SettingsDep,
)
from payflow.presentation.consumer.schemas import PaymentCreatedMessage

logger = logging.getLogger(__name__)


def create_worker(settings: ServiceConfig | None = None) -> FastStream:
    settings = settings or ServiceConfig()
    broker = RabbitBroker(settings.broker.url)

    @asynccontextmanager
    async def lifespan(context: ContextRepo) -> AsyncIterator[None]:
        async with (
            open_resources(settings) as resources,
            httpx.AsyncClient(timeout=settings.webhook.timeout_seconds) as http_client,
        ):
            context.set_global(RESOURCES_KEY, resources)
            context.set_global(HTTP_CLIENT_KEY, http_client)
            context.set_global(BROKER_KEY, broker)
            yield

    app = FastStream(broker, lifespan=lifespan)

    @app.after_startup
    async def setup() -> None:
        await declare_payments_topology(
            broker,
            retry_max_attempts=settings.broker.retry_max_attempts,
            retry_base_delay_seconds=settings.broker.retry_base_delay_seconds,
        )

    @broker.subscriber(PAYMENTS_NEW_QUEUE, PAYMENTS_EXCHANGE, ack_policy=AckPolicy.MANUAL)
    async def consume_payment_created(
        body: dict[str, object],
        message: RabbitMessage,
        service: ProcessPaymentDep,
        retry_publisher: RetryPublisherDep,
        config: SettingsDep,
    ) -> None:
        try:
            event = PaymentCreatedMessage.model_validate(body)
        except ValidationError:
            logger.warning("invalid payment message", extra={"body": body})
            await message.reject(requeue=False)
            return

        try:
            await service.execute(event.payment_id)
        except PaymentProcessingFailedError:
            next_attempt = event.retry_attempt + 1
            if next_attempt < config.broker.retry_max_attempts:
                await retry_publisher.publish_retry(
                    payload=event.model_dump(mode="json", by_alias=True),
                    attempt=next_attempt,
                )
                logger.warning(
                    "payment message scheduled for retry",
                    extra={
                        "payment_id": str(event.payment_id),
                        "retry_attempt": next_attempt,
                        "delay_ms": payment_retry_delay_ms(
                            attempt=next_attempt,
                            base_delay_seconds=config.broker.retry_base_delay_seconds,
                        ),
                    },
                )
                await message.ack()
                return
            logger.exception(
                "payment message moved to dlq", extra={"payment_id": str(event.payment_id)}
            )
            await message.reject(requeue=False)
            return

        await message.ack()

    @broker.subscriber(PAYMENTS_NEW_DLQ)
    async def consume_dead_letter(body: dict[str, object], message: RabbitMessage) -> None:
        logger.error("dead-letter payment message", extra={"body": body})
        await message.ack()

    return app
