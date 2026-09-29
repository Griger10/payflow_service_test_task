import asyncio
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payflow.application.interfaces import EventPublisher
from payflow.application.services import PublishOutbox
from payflow.domain import OutboxEvent
from payflow.domain.enums import OutboxStatus
from payflow.infra.database import SqlAlchemyUnitOfWork
from payflow.infra.database.models import OutboxModel
from tests.conftest import CREATED_AT, FIXED_NOW, FixedClock

EVENT_ID = UUID("00000000-0000-0000-0000-000000000001")
MAX_ATTEMPTS = 2


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[UUID] = []

    async def publish(
        self, *, routing_key: str, payload: Mapping[str, Any], message_id: UUID
    ) -> None:
        self.published.append(message_id)


class FailingPublisher:
    async def publish(
        self, *, routing_key: str, payload: Mapping[str, Any], message_id: UUID
    ) -> None:
        raise ConnectionError("broker unavailable")


class HangingPublisher:
    async def publish(
        self, *, routing_key: str, payload: Mapping[str, Any], message_id: UUID
    ) -> None:
        await asyncio.sleep(3600)


class LockProbePublisher:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.lock_acquired = False

    async def publish(
        self, *, routing_key: str, payload: Mapping[str, Any], message_id: UUID
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                select(OutboxModel.id)
                .where(OutboxModel.id == message_id)
                .with_for_update(nowait=True)
            )
            self.lock_acquired = True


@pytest.fixture
def relay_factory(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork], fixed_clock: FixedClock
) -> Callable[..., PublishOutbox]:
    def build(publisher: EventPublisher, *, publish_timeout_seconds: float = 5.0) -> PublishOutbox:
        return PublishOutbox(
            uow_factory=uow_factory,
            publisher=publisher,
            clock=fixed_clock,
            max_attempts=MAX_ATTEMPTS,
            base_delay_seconds=2.0,
            lease_seconds=30.0,
            publish_timeout_seconds=publish_timeout_seconds,
        )

    return build


@pytest.fixture
async def stored_event(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    outbox_event_factory: Callable[..., OutboxEvent],
) -> UUID:
    async with uow_factory() as uow:
        await uow.outbox.add(
            outbox_event_factory(
                event_id=EVENT_ID, payload={"payment_id": "1"}, created_at=CREATED_AT
            )
        )
        await uow.commit()
    return EVENT_ID


async def _load(session_factory: async_sessionmaker[AsyncSession]) -> OutboxModel:
    async with session_factory() as session:
        row = await session.get(OutboxModel, EVENT_ID)
    assert row is not None
    return row


@pytest.mark.asyncio
async def test_relay_publishes_event_and_releases_lease(
    relay_factory: Callable[..., PublishOutbox],
    session_factory: async_sessionmaker[AsyncSession],
    stored_event: UUID,
) -> None:
    publisher = RecordingPublisher()

    result = await relay_factory(publisher).publish_batch(batch_size=10)
    row = await _load(session_factory)

    assert (result.published, result.failed) == (1, 0)
    assert publisher.published == [stored_event]
    assert row.status == OutboxStatus.PUBLISHED
    assert row.published_at == FIXED_NOW
    assert row.locked_until is None


@pytest.mark.asyncio
async def test_relay_schedules_retry_with_backoff_then_marks_failed(
    relay_factory: Callable[..., PublishOutbox],
    session_factory: async_sessionmaker[AsyncSession],
    stored_event: UUID,
) -> None:
    del stored_event
    relay = relay_factory(FailingPublisher())

    first = await relay.publish_batch(batch_size=10)
    after_first = await _load(session_factory)
    async with session_factory() as session:
        row = await session.get(OutboxModel, EVENT_ID)
        assert row is not None
        row.next_attempt_at = FIXED_NOW - timedelta(seconds=1)
        await session.commit()
    second = await relay.publish_batch(batch_size=10)
    after_second = await _load(session_factory)

    assert (first.published, first.failed) == (0, 0)
    assert after_first.status == OutboxStatus.PENDING
    assert after_first.attempts == 1
    assert after_first.next_attempt_at == FIXED_NOW + timedelta(seconds=2)
    assert after_first.locked_until is None
    assert "ConnectionError" in (after_first.last_error or "")
    assert (second.published, second.failed) == (0, 1)
    assert after_second.status == OutboxStatus.FAILED
    assert after_second.attempts == MAX_ATTEMPTS
    assert after_second.locked_until is None


@pytest.mark.asyncio
async def test_relay_treats_publish_timeout_as_failure(
    relay_factory: Callable[..., PublishOutbox],
    session_factory: async_sessionmaker[AsyncSession],
    stored_event: UUID,
) -> None:
    del stored_event

    await relay_factory(HangingPublisher(), publish_timeout_seconds=0.05).publish_batch(
        batch_size=10
    )
    row = await _load(session_factory)

    assert row.status == OutboxStatus.PENDING
    assert row.attempts == 1
    assert "TimeoutError" in (row.last_error or "")


@pytest.mark.asyncio
async def test_relay_publishes_without_holding_row_lock(
    relay_factory: Callable[..., PublishOutbox],
    session_factory: async_sessionmaker[AsyncSession],
    stored_event: UUID,
) -> None:
    del stored_event
    publisher = LockProbePublisher(session_factory)

    await relay_factory(publisher).publish_batch(batch_size=10)

    assert publisher.lock_acquired is True
