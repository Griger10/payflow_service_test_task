from payflow.infra.config import OutboxConfig, ProcessingConfig, ServiceConfig, WebhookConfig


def test_config_exposes_typed_runtime_sections() -> None:
    config = ServiceConfig(
        API_KEY="test-key",
        DATABASE_URL="postgresql+asyncpg://db/payments",
        RABBITMQ_URL="amqp://broker/",
    )

    assert config.api.key == "test-key"
    assert config.database.url == "postgresql+asyncpg://db/payments"
    assert config.broker.url == "amqp://broker/"
    assert config.processing == ProcessingConfig(
        success_rate=0.9,
        min_delay_seconds=2.0,
        max_delay_seconds=5.0,
    )
    assert config.webhook == WebhookConfig(timeout_seconds=5.0)
    assert config.outbox == OutboxConfig(
        batch_size=50,
        poll_interval_seconds=1.0,
        max_attempts=10,
        retry_base_delay_seconds=1.0,
        lease_seconds=60.0,
        publish_timeout_seconds=10.0,
    )
