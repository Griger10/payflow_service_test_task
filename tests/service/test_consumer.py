from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from fast_depends import dependency_provider
from faststream import FastStream
from faststream.rabbit import RabbitBroker, TestRabbitBroker

from payflow.application.errors import PaymentProcessingFailedError
from payflow.bootstrap.resources import open_resources
from payflow.infra.config import ServiceConfig
from payflow.infra.messaging.topology import PAYMENTS_EXCHANGE
from payflow.presentation.consumer.app import create_worker
from payflow.presentation.consumer.dependencies import (
    BROKER_KEY,
    HTTP_CLIENT_KEY,
    RESOURCES_KEY,
    get_process_payment,
    get_retry_publisher,
)

PAYMENT_ID = UUID("00000000-0000-0000-0000-000000000001")
MESSAGE = {
    "payment_id": str(PAYMENT_ID),
    "idempotency_key": "idem-1",
    "created_at": "2026-08-04T11:00:00+00:00",
}


class FakeProcessPayment:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[UUID] = []
        self._fail = fail

    async def execute(self, payment_id: UUID) -> None:
        self.calls.append(payment_id)
        if self._fail:
            raise PaymentProcessingFailedError(payment_id, RuntimeError("gateway down"))


class FakeRetryPublisher:
    def __init__(self) -> None:
        self.attempts: list[int] = []

    async def publish_retry(self, *, payload: Mapping[str, Any], attempt: int) -> None:
        self.attempts.append(attempt)


def _broker(app: FastStream) -> RabbitBroker:
    assert isinstance(app.broker, RabbitBroker)
    return app.broker


@pytest_asyncio.fixture
async def worker(test_settings: ServiceConfig) -> AsyncIterator[FastStream]:
    app = create_worker(test_settings)
    async with (
        open_resources(test_settings) as resources,
        httpx.AsyncClient() as http_client,
    ):
        app.context.set_global(RESOURCES_KEY, resources)
        app.context.set_global(HTTP_CLIENT_KEY, http_client)
        app.context.set_global(BROKER_KEY, _broker(app))
        try:
            yield app
        finally:
            dependency_provider.clear()


@pytest.fixture
def override() -> Callable[[Callable[..., Any], object], None]:
    def apply(provider: Callable[..., Any], replacement: object) -> None:
        dependency_provider.override(provider, lambda: replacement)

    return apply


@pytest.mark.asyncio
async def test_consumer_resolves_service_through_depends(
    worker: FastStream, override: Callable[[Callable[..., Any], object], None]
) -> None:
    service = FakeProcessPayment()
    override(get_process_payment, service)

    async with TestRabbitBroker(_broker(worker)) as broker:
        await broker.publish(MESSAGE, exchange=PAYMENTS_EXCHANGE, routing_key="payments.new")

    assert service.calls == [PAYMENT_ID]


@pytest.mark.asyncio
async def test_consumer_schedules_retry_when_processing_fails(
    worker: FastStream, override: Callable[[Callable[..., Any], object], None]
) -> None:
    service = FakeProcessPayment(fail=True)
    retry_publisher = FakeRetryPublisher()
    override(get_process_payment, service)
    override(get_retry_publisher, retry_publisher)

    async with TestRabbitBroker(_broker(worker)) as broker:
        await broker.publish(MESSAGE, exchange=PAYMENTS_EXCHANGE, routing_key="payments.new")

    assert service.calls == [PAYMENT_ID]
    assert retry_publisher.attempts == [1]
