import asyncio
import logging

from faststream.rabbit import RabbitBroker

from payflow.bootstrap.factories import make_publish_outbox, make_uow_factory
from payflow.bootstrap.resources import open_resources
from payflow.infra.config import ServiceConfig
from payflow.infra.integrations.clock import SystemClock
from payflow.infra.messaging.declaration import declare_payments_topology
from payflow.infra.messaging.publisher import RabbitEventPublisher

logger = logging.getLogger(__name__)


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = ServiceConfig()
    broker = RabbitBroker(settings.broker.url)
    async with open_resources(settings) as resources:
        await broker.connect()
        try:
            await declare_payments_topology(
                broker,
                retry_max_attempts=settings.broker.retry_max_attempts,
                retry_base_delay_seconds=settings.broker.retry_base_delay_seconds,
            )
            relay = make_publish_outbox(
                uow_factory=make_uow_factory(resources.session_factory),
                publisher=RabbitEventPublisher(broker),
                clock=SystemClock(),
                config=settings.outbox,
            )
            while True:
                result = await relay.publish_batch(batch_size=settings.outbox.batch_size)
                if result.published or result.failed:
                    logger.info(
                        "outbox relay iteration completed",
                        extra={"published": result.published, "failed": result.failed},
                    )
                await asyncio.sleep(settings.outbox.poll_interval_seconds)
        finally:
            await broker.stop()


if __name__ == "__main__":
    asyncio.run(run())
