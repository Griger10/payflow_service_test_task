"""Framework-agnostic builders shared by every composition root."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payflow.application.interfaces import (
    Clock,
    EventPublisher,
    IdGenerator,
    PaymentGateway,
    UnitOfWorkFactory,
    WebhookClient,
)
from payflow.application.services import CreatePayment, GetPayment, ProcessPayment, PublishOutbox
from payflow.infra.config import OutboxConfig, ProcessingConfig
from payflow.infra.database import SqlAlchemyUnitOfWork
from payflow.infra.integrations.payment_gateway import SimulatedPaymentGateway
from payflow.infra.integrations.webhook import HttpxWebhookClient


def make_uow_factory(session_factory: async_sessionmaker[AsyncSession]) -> UnitOfWorkFactory:
    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    return uow_factory


def make_gateway(config: ProcessingConfig) -> PaymentGateway:
    return SimulatedPaymentGateway(
        min_delay_seconds=config.min_delay_seconds,
        max_delay_seconds=config.max_delay_seconds,
        success_rate=config.success_rate,
    )


def make_webhook_client(http_client: httpx.AsyncClient) -> WebhookClient:
    return HttpxWebhookClient(http_client)


def make_create_payment(
    *, uow_factory: UnitOfWorkFactory, clock: Clock, id_generator: IdGenerator
) -> CreatePayment:
    return CreatePayment(uow_factory=uow_factory, clock=clock, id_generator=id_generator)


def make_get_payment(*, uow_factory: UnitOfWorkFactory) -> GetPayment:
    return GetPayment(uow_factory=uow_factory)


def make_process_payment(
    *,
    uow_factory: UnitOfWorkFactory,
    payment_gateway: PaymentGateway,
    webhook_client: WebhookClient,
    clock: Clock,
) -> ProcessPayment:
    return ProcessPayment(
        uow_factory=uow_factory,
        payment_gateway=payment_gateway,
        webhook_client=webhook_client,
        clock=clock,
    )


def make_publish_outbox(
    *,
    uow_factory: UnitOfWorkFactory,
    publisher: EventPublisher,
    clock: Clock,
    config: OutboxConfig,
) -> PublishOutbox:
    return PublishOutbox(
        uow_factory=uow_factory,
        publisher=publisher,
        clock=clock,
        max_attempts=config.max_attempts,
        base_delay_seconds=config.retry_base_delay_seconds,
        lease_seconds=config.lease_seconds,
        publish_timeout_seconds=config.publish_timeout_seconds,
    )
