import os
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from payflow.application.services import ProcessPayment
from payflow.bootstrap.resources import open_resources
from payflow.domain import JsonObject, OutboxEvent, Payment
from payflow.domain.enums import Currency, PaymentStatus
from payflow.infra.config import ServiceConfig
from payflow.infra.database import SqlAlchemyUnitOfWork
from payflow.infra.database.models import Base
from payflow.presentation.api.app import create_app
from payflow.presentation.api.dependencies import get_resources

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/payments",
)
FIXED_NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
CREATED_AT = datetime(2026, 8, 4, 11, 0, tzinfo=UTC)
API_KEY = "test-api-key"


class FixedClock:
    def now(self) -> datetime:
        return FIXED_NOW


class SuccessfulGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def process(self, payment: Payment) -> PaymentStatus:
        self.calls += 1
        return PaymentStatus.SUCCEEDED


class FlakyWebhook:
    def __init__(self) -> None:
        self.calls = 0
        self.delivery_ids: list[UUID] = []

    async def send(self, url: str, payload: Mapping[str, Any], *, delivery_id: UUID) -> None:
        self.calls += 1
        self.delivery_ids.append(delivery_id)
        if self.calls == 1:
            raise RuntimeError("temporary webhook failure")


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], SqlAlchemyUnitOfWork]:
    return lambda: SqlAlchemyUnitOfWork(session_factory)


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def successful_gateway() -> SuccessfulGateway:
    return SuccessfulGateway()


@pytest.fixture
def flaky_webhook() -> FlakyWebhook:
    return FlakyWebhook()


@pytest.fixture
def payment_processing_service(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    successful_gateway: SuccessfulGateway,
    flaky_webhook: FlakyWebhook,
    fixed_clock: FixedClock,
) -> ProcessPayment:
    return ProcessPayment(
        uow_factory=uow_factory,
        payment_gateway=successful_gateway,
        webhook_client=flaky_webhook,
        clock=fixed_clock,
    )


@pytest.fixture
def payment_factory() -> Callable[..., Payment]:
    def build(
        *,
        payment_id: UUID | None = None,
        amount: Decimal = Decimal("100.00"),
        currency: Currency = Currency.RUB,
        description: str = "order 42",
        metadata: JsonObject | None = None,
        status: PaymentStatus = PaymentStatus.PENDING,
        idempotency_key: str = "idem-1",
        webhook_url: str = "https://client.example/webhook",
        created_at: datetime = CREATED_AT,
    ) -> Payment:
        return Payment(
            id=payment_id or uuid4(),
            amount=amount,
            currency=currency,
            description=description,
            metadata=metadata or {"order_id": "42"},
            status=status,
            idempotency_key=idempotency_key,
            webhook_url=webhook_url,
            created_at=created_at,
        )

    return build


@pytest.fixture
def outbox_event_factory() -> Callable[..., OutboxEvent]:
    def build(
        *,
        event_id: UUID,
        payload: JsonObject,
        created_at: datetime,
        event_type: str = "payment.created",
        routing_key: str = "payments.new",
    ) -> OutboxEvent:
        return OutboxEvent(
            id=event_id,
            event_type=event_type,
            routing_key=routing_key,
            payload=payload,
            created_at=created_at,
        )

    return build


@pytest.fixture
def test_settings() -> ServiceConfig:
    return ServiceConfig(
        API_KEY=API_KEY,
        DATABASE_URL=TEST_DATABASE_URL,
        RABBITMQ_URL="amqp://guest:guest@localhost:5672/",
    )


@pytest_asyncio.fixture
async def api_app(engine: AsyncEngine, test_settings: ServiceConfig) -> AsyncIterator[FastAPI]:
    del engine
    app = create_app(test_settings)
    async with open_resources(test_settings) as resources:
        app.dependency_overrides[get_resources] = lambda: resources
        yield app


@pytest_asyncio.fixture
async def api_client(api_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
