import asyncio
from dataclasses import dataclass
from datetime import timedelta

from payflow.application.interfaces import Clock, EventPublisher, UnitOfWorkFactory
from payflow.domain import OutboxEvent


@dataclass(frozen=True, slots=True)
class OutboxRelayResult:
    published: int = 0
    failed: int = 0


class PublishOutbox:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        publisher: EventPublisher,
        clock: Clock,
        max_attempts: int,
        base_delay_seconds: float,
        lease_seconds: float,
        publish_timeout_seconds: float,
    ) -> None:
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._clock = clock
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._lease_seconds = lease_seconds
        self._publish_timeout_seconds = publish_timeout_seconds

    async def publish_batch(self, *, batch_size: int) -> OutboxRelayResult:
        events = await self._claim(batch_size)
        published = 0
        failed = 0
        for event in events:
            try:
                async with asyncio.timeout(self._publish_timeout_seconds):
                    await self._publisher.publish(
                        routing_key=event.routing_key, payload=event.payload, message_id=event.id
                    )
            except Exception as exc:
                if await self._record_failure(event, exc):
                    failed += 1
            else:
                await self._record_published(event)
                published += 1
        return OutboxRelayResult(published=published, failed=failed)

    async def _claim(self, batch_size: int) -> list[OutboxEvent]:
        async with self._uow_factory() as uow:
            now = self._clock.now()
            events = await uow.outbox.claim_ready(
                limit=batch_size,
                now=now,
                lease_until=now + timedelta(seconds=self._lease_seconds),
            )
            await uow.commit()
        return events

    async def _record_published(self, event: OutboxEvent) -> None:
        async with self._uow_factory() as uow:
            await uow.outbox.mark_published(event.id, published_at=self._clock.now())
            await uow.commit()

    async def _record_failure(self, event: OutboxEvent, exc: Exception) -> bool:
        attempts = event.attempts + 1
        terminal = attempts >= self._max_attempts
        async with self._uow_factory() as uow:
            if terminal:
                await uow.outbox.mark_failed(event.id, attempts=attempts, error=_error_message(exc))
            else:
                await uow.outbox.mark_retry(
                    event.id,
                    attempts=attempts,
                    next_attempt_at=self._clock.now() + self._delay(attempts),
                    error=_error_message(exc),
                )
            await uow.commit()
        return terminal

    def _delay(self, attempts: int) -> timedelta:
        return timedelta(seconds=self._base_delay_seconds * 2 ** (attempts - 1))


def _error_message(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]
