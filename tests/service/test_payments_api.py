import asyncio
from collections.abc import MutableMapping
from http import HTTPStatus
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payflow.bootstrap.resources import Resources
from payflow.infra.config import ServiceConfig
from payflow.infra.database.models import OutboxModel, PaymentModel
from payflow.presentation.api.app import create_app
from payflow.presentation.api.dependencies import get_clock, get_id_generator
from tests.conftest import FixedClock


class FixedIds:
    def __init__(self, value: UUID) -> None:
        self._value = value

    def new_uuid(self) -> UUID:
        return self._value


@pytest.mark.asyncio
async def test_create_and_get_payment_through_api_with_real_database(
    api_client: httpx.AsyncClient,
) -> None:
    create_response = await api_client.post(
        "/api/v1/payments",
        headers={
            "X-API-Key": "test-api-key",
            "Idempotency-Key": "api-idem-1",
        },
        json={
            "amount": "125.00",
            "currency": "EUR",
            "description": "invoice 77",
            "metadata": {"invoice_id": "77"},
            "webhook_url": "https://client.example/webhook",
        },
    )

    assert create_response.status_code == HTTPStatus.ACCEPTED
    body = create_response.json()
    assert body["status"] == "pending"

    get_response = await api_client.get(
        f"/api/v1/payments/{body['payment_id']}",
        headers={"X-API-Key": "test-api-key"},
    )

    assert get_response.status_code == HTTPStatus.OK
    details = get_response.json()
    assert details["payment_id"] == body["payment_id"]
    assert details["amount"] == "125.00"
    assert details["currency"] == "EUR"
    assert details["idempotency_key"] == "api-idem-1"


@pytest.mark.asyncio
async def test_concurrent_create_payment_uses_one_idempotent_record(
    api_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def create_payment() -> httpx.Response:
        return await api_client.post(
            "/api/v1/payments",
            headers={
                "X-API-Key": "test-api-key",
                "Idempotency-Key": "api-idem-race",
            },
            json={
                "amount": "125.00",
                "currency": "EUR",
                "description": "invoice 88",
                "metadata": {"invoice_id": "88"},
                "webhook_url": "https://client.example/webhook",
            },
        )

    responses = await asyncio.gather(*(create_payment() for _ in range(8)))
    bodies = [response.json() for response in responses]

    async with session_factory() as session:
        payment_count = await session.scalar(
            select(func.count(PaymentModel.id)).where(
                PaymentModel.idempotency_key == "api-idem-race"
            )
        )
        outbox_count = await session.scalar(select(func.count(OutboxModel.id)))

    assert [response.status_code for response in responses] == [HTTPStatus.ACCEPTED] * 8
    assert {body["payment_id"] for body in bodies} == {bodies[0]["payment_id"]}
    assert payment_count == 1
    assert outbox_count == 1


@pytest.mark.asyncio
async def test_api_dependencies_can_be_overridden_per_test(
    api_app: FastAPI,
    api_client: httpx.AsyncClient,
) -> None:
    fixed_id = UUID("00000000-0000-0000-0000-0000000000aa")
    api_app.dependency_overrides[get_clock] = FixedClock
    api_app.dependency_overrides[get_id_generator] = lambda: FixedIds(fixed_id)

    response = await api_client.post(
        "/api/v1/payments",
        headers={"X-API-Key": "test-api-key", "Idempotency-Key": "override-1"},
        json={
            "amount": "10.00",
            "currency": "RUB",
            "description": "override",
            "metadata": {},
            "webhook_url": "https://client.example/webhook",
        },
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    assert response.json()["payment_id"] == str(fixed_id)
    assert response.json()["created_at"].startswith("2026-08-04T12:00:00")


@pytest.mark.asyncio
async def test_lifespan_exposes_resources_to_dependencies(test_settings: ServiceConfig) -> None:
    app = create_app(test_settings)
    state: dict[str, Any] = {}
    scope: MutableMapping[str, Any] = {
        "type": "lifespan",
        "asgi": {"version": "3.0"},
        "state": state,
    }
    inbox: asyncio.Queue[MutableMapping[str, Any]] = asyncio.Queue()
    outbox: asyncio.Queue[MutableMapping[str, Any]] = asyncio.Queue()

    task = asyncio.create_task(app(scope, inbox.get, outbox.put))
    await inbox.put({"type": "lifespan.startup"})
    assert (await outbox.get())["type"] == "lifespan.startup.complete"
    assert isinstance(state["resources"], Resources)
    await inbox.put({"type": "lifespan.shutdown"})
    assert (await outbox.get())["type"] == "lifespan.shutdown.complete"
    await task
