from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payflow.domain import OutboxEvent, Payment
from payflow.domain.enums import OutboxStatus
from payflow.infra.database import SqlAlchemyUnitOfWork
from payflow.infra.database.models import OutboxModel


@pytest.mark.asyncio
async def test_payment_repository_round_trips_domain_entity(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    payment_factory: Callable[..., Payment],
) -> None:
    payment_id = UUID("00000000-0000-0000-0000-000000000001")
    payment = payment_factory(payment_id=payment_id)

    async with uow_factory() as uow:
        await uow.payments.add(payment)
        await uow.commit()

    async with uow_factory() as uow:
        loaded = await uow.payments.get_by_id(payment_id)
        by_key = await uow.payments.get_by_idempotency_key("idem-1")

    assert loaded == payment
    assert by_key == payment


@pytest.mark.asyncio
async def test_payment_repository_reports_duplicate_idempotency_key(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    payment_factory: Callable[..., Payment],
) -> None:
    first_payment_id = UUID("00000000-0000-0000-0000-000000000001")
    second_payment_id = UUID("00000000-0000-0000-0000-000000000002")

    async with uow_factory() as uow:
        inserted = await uow.payments.add(payment_factory(payment_id=first_payment_id))
        await uow.commit()

    async with uow_factory() as uow:
        duplicate_inserted = await uow.payments.add(
            payment_factory(payment_id=second_payment_id, description="changed")
        )
        await uow.commit()

    async with uow_factory() as uow:
        first = await uow.payments.get_by_id(first_payment_id)
        duplicate = await uow.payments.get_by_id(second_payment_id)

    assert inserted is True
    assert duplicate_inserted is False
    assert first is not None
    assert duplicate is None


@pytest.mark.asyncio
async def test_webhook_delivery_repository_marks_payment_once(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    payment_factory: Callable[..., Payment],
) -> None:
    payment_id = UUID("00000000-0000-0000-0000-000000000001")
    delivered_at = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    async with uow_factory() as uow:
        await uow.payments.add(payment_factory(payment_id=payment_id))
        await uow.commit()

    async with uow_factory() as uow:
        first_mark = await uow.webhook_deliveries.mark_delivered(
            payment_id, delivered_at=delivered_at
        )
        second_mark = await uow.webhook_deliveries.mark_delivered(
            payment_id, delivered_at=delivered_at + timedelta(seconds=1)
        )
        await uow.commit()

    async with uow_factory() as uow:
        delivered = await uow.webhook_deliveries.is_delivered(payment_id)

    assert first_mark is True
    assert second_mark is False
    assert delivered is True


@pytest.mark.asyncio
async def test_outbox_repository_returns_ready_events_in_deterministic_order(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    outbox_event_factory: Callable[..., OutboxEvent],
) -> None:
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    event_ids = [
        UUID("00000000-0000-0000-0000-000000000002"),
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000003"),
    ]
    async with uow_factory() as uow:
        await uow.outbox.add(
            outbox_event_factory(
                event_id=event_ids[0],
                payload={"payment_id": "2"},
                created_at=now,
            ),
        )
        await uow.outbox.add(
            outbox_event_factory(
                event_id=event_ids[1],
                payload={"payment_id": "1"},
                created_at=now,
            ),
        )
        await uow.commit()

    async with session_factory() as session:
        session.add(
            OutboxModel(
                id=event_ids[2],
                event_type="payment.created",
                routing_key="payments.new",
                payload={"payment_id": "3"},
                status=OutboxStatus.PENDING,
                attempts=0,
                next_attempt_at=now + timedelta(minutes=5),
                created_at=now - timedelta(minutes=1),
            ),
        )
        await session.commit()

    async with uow_factory() as uow:
        ready = await uow.outbox.claim_ready(
            limit=10, now=now, lease_until=now + timedelta(seconds=30)
        )
        await uow.commit()

    assert [event.id for event in ready] == [event_ids[1], event_ids[0]]


@pytest.mark.asyncio
async def test_outbox_claim_skips_leased_events_until_lease_expires(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    outbox_event_factory: Callable[..., OutboxEvent],
) -> None:
    event_id = UUID("00000000-0000-0000-0000-000000000001")
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    lease_until = now + timedelta(seconds=30)
    async with uow_factory() as uow:
        await uow.outbox.add(
            outbox_event_factory(event_id=event_id, payload={"payment_id": "1"}, created_at=now)
        )
        await uow.commit()

    async def claim(at: datetime) -> list[OutboxEvent]:
        async with uow_factory() as uow:
            events = await uow.outbox.claim_ready(
                limit=10, now=at, lease_until=at + timedelta(seconds=30)
            )
            await uow.commit()
        return events

    first = await claim(now)
    while_leased = await claim(lease_until - timedelta(seconds=1))
    after_expiry = await claim(lease_until)

    assert [event.id for event in first] == [event_id]
    assert while_leased == []
    assert [event.id for event in after_expiry] == [event_id]


@pytest.mark.asyncio
async def test_outbox_concurrent_claims_return_disjoint_events(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    outbox_event_factory: Callable[..., OutboxEvent],
) -> None:
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    lease_until = now + timedelta(seconds=30)
    event_ids = [UUID(int=index) for index in range(1, 5)]
    async with uow_factory() as uow:
        for event_id in event_ids:
            await uow.outbox.add(
                outbox_event_factory(event_id=event_id, payload={}, created_at=now)
            )
        await uow.commit()

    async with uow_factory() as first_uow, uow_factory() as second_uow:
        first = await first_uow.outbox.claim_ready(limit=2, now=now, lease_until=lease_until)
        second = await second_uow.outbox.claim_ready(limit=2, now=now, lease_until=lease_until)
        await first_uow.commit()
        await second_uow.commit()

    claimed = {event.id for event in first} | {event.id for event in second}
    assert len(first) == len(second) == 2  # noqa: PLR2004
    assert claimed == set(event_ids)


@pytest.mark.asyncio
async def test_outbox_repository_persists_retry_and_published_states(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    outbox_event_factory: Callable[..., OutboxEvent],
) -> None:
    event_id = UUID("00000000-0000-0000-0000-000000000001")
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    async with uow_factory() as uow:
        await uow.outbox.add(
            outbox_event_factory(
                event_id=event_id,
                payload={"payment_id": "1"},
                created_at=now,
            ),
        )
        await uow.outbox.mark_retry(
            event_id,
            attempts=1,
            next_attempt_at=now + timedelta(seconds=2),
            error="broker unavailable",
        )
        await uow.commit()

    async with session_factory() as session:
        row = await session.get(OutboxModel, event_id)

    assert row is not None
    assert row.status == OutboxStatus.PENDING
    assert row.attempts == 1
    assert row.next_attempt_at == now + timedelta(seconds=2)
    assert row.last_error == "broker unavailable"

    async with uow_factory() as uow:
        await uow.outbox.mark_published(event_id, published_at=now + timedelta(seconds=3))
        await uow.commit()

    async with session_factory() as session:
        statuses = (await session.execute(select(OutboxModel.status))).scalars().all()

    assert statuses == [OutboxStatus.PUBLISHED]
