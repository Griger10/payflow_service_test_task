from payflow.infra.messaging.topology import (
    payment_retry_delay_ms,
    payment_retry_routing_key,
)

EXPECTED_RETRY_DELAY_MS = 6000


def test_payment_retry_routing_key_and_delay_are_deterministic() -> None:
    assert payment_retry_routing_key(2) == "payments.new.retry.2"
    assert payment_retry_delay_ms(attempt=3, base_delay_seconds=1.5) == EXPECTED_RETRY_DELAY_MS
