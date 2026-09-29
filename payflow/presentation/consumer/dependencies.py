from typing import Annotated, Final

import httpx
from faststream import Context, Depends
from faststream.rabbit import RabbitBroker

from payflow.application.interfaces import Clock, PaymentGateway, UnitOfWorkFactory, WebhookClient
from payflow.application.services import ProcessPayment
from payflow.bootstrap.factories import (
    make_gateway,
    make_process_payment,
    make_uow_factory,
    make_webhook_client,
)
from payflow.bootstrap.resources import Resources
from payflow.infra.config import ServiceConfig
from payflow.infra.integrations.clock import SystemClock
from payflow.infra.messaging.retry import RabbitPaymentRetryPublisher

RESOURCES_KEY: Final = "resources"
HTTP_CLIENT_KEY: Final = "http_client"
BROKER_KEY: Final = "broker"


def get_resources(resources: Annotated[Resources, Context(RESOURCES_KEY)]) -> Resources:
    return resources


ResourcesDep = Annotated[Resources, Depends(get_resources, cast=False)]


def get_settings(resources: ResourcesDep) -> ServiceConfig:
    return resources.settings


SettingsDep = Annotated[ServiceConfig, Depends(get_settings, cast=False)]


def get_clock() -> Clock:
    return SystemClock()


ClockDep = Annotated[Clock, Depends(get_clock, cast=False)]


def get_uow_factory(resources: ResourcesDep) -> UnitOfWorkFactory:
    return make_uow_factory(resources.session_factory)


UowFactoryDep = Annotated[UnitOfWorkFactory, Depends(get_uow_factory, cast=False)]


def get_gateway(settings: SettingsDep) -> PaymentGateway:
    return make_gateway(settings.processing)


GatewayDep = Annotated[PaymentGateway, Depends(get_gateway, cast=False)]


def get_webhook_client(
    http_client: Annotated[httpx.AsyncClient, Context(HTTP_CLIENT_KEY)],
) -> WebhookClient:
    return make_webhook_client(http_client)


WebhookClientDep = Annotated[WebhookClient, Depends(get_webhook_client, cast=False)]


def get_process_payment(
    uow_factory: UowFactoryDep,
    gateway: GatewayDep,
    webhook_client: WebhookClientDep,
    clock: ClockDep,
) -> ProcessPayment:
    return make_process_payment(
        uow_factory=uow_factory,
        payment_gateway=gateway,
        webhook_client=webhook_client,
        clock=clock,
    )


ProcessPaymentDep = Annotated[ProcessPayment, Depends(get_process_payment, cast=False)]


def get_retry_publisher(
    broker: Annotated[RabbitBroker, Context(BROKER_KEY)],
) -> RabbitPaymentRetryPublisher:
    return RabbitPaymentRetryPublisher(broker)


RetryPublisherDep = Annotated[RabbitPaymentRetryPublisher, Depends(get_retry_publisher, cast=False)]
