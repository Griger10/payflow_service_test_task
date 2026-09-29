from dataclasses import dataclass

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True, slots=True)
class ApiConfig:
    key: str


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    url: str


@dataclass(frozen=True, slots=True)
class BrokerConfig:
    url: str
    retry_max_attempts: int
    retry_base_delay_seconds: float


@dataclass(frozen=True, slots=True)
class ProcessingConfig:
    success_rate: float
    min_delay_seconds: float
    max_delay_seconds: float


@dataclass(frozen=True, slots=True)
class WebhookConfig:
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class OutboxConfig:
    batch_size: int
    poll_interval_seconds: float
    max_attempts: int
    retry_base_delay_seconds: float
    lease_seconds: float
    publish_timeout_seconds: float


class ServiceConfig(BaseSettings):
    api_key: str = Field(default="secret-api-key", alias="API_KEY")
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/payments",
        alias="DATABASE_URL",
    )
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/", alias="RABBITMQ_URL")
    payment_success_rate: float = Field(default=0.9, alias="PAYMENT_SUCCESS_RATE")
    payment_min_delay_seconds: float = Field(default=2.0, alias="PAYMENT_MIN_DELAY_SECONDS")
    payment_max_delay_seconds: float = Field(default=5.0, alias="PAYMENT_MAX_DELAY_SECONDS")
    retry_max_attempts: int = Field(default=3, alias="RETRY_MAX_ATTEMPTS")
    retry_base_delay_seconds: float = Field(default=1.0, alias="RETRY_BASE_DELAY_SECONDS")
    webhook_timeout_seconds: float = Field(default=5.0, alias="WEBHOOK_TIMEOUT_SECONDS")
    outbox_batch_size: int = Field(default=50, alias="OUTBOX_BATCH_SIZE")
    outbox_poll_interval_seconds: float = Field(default=1.0, alias="OUTBOX_POLL_INTERVAL_SECONDS")
    outbox_max_attempts: int = Field(default=10, alias="OUTBOX_MAX_ATTEMPTS")
    outbox_retry_base_delay_seconds: float = Field(
        default=1.0, alias="OUTBOX_RETRY_BASE_DELAY_SECONDS"
    )
    outbox_lease_seconds: float = Field(default=60.0, alias="OUTBOX_LEASE_SECONDS")
    outbox_publish_timeout_seconds: float = Field(
        default=10.0, alias="OUTBOX_PUBLISH_TIMEOUT_SECONDS"
    )
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def api(self) -> ApiConfig:
        return ApiConfig(key=self.api_key)

    @property
    def database(self) -> DatabaseConfig:
        return DatabaseConfig(url=self.database_url)

    @property
    def broker(self) -> BrokerConfig:
        return BrokerConfig(
            url=self.rabbitmq_url,
            retry_max_attempts=self.retry_max_attempts,
            retry_base_delay_seconds=self.retry_base_delay_seconds,
        )

    @property
    def processing(self) -> ProcessingConfig:
        return ProcessingConfig(
            success_rate=self.payment_success_rate,
            min_delay_seconds=self.payment_min_delay_seconds,
            max_delay_seconds=self.payment_max_delay_seconds,
        )

    @property
    def webhook(self) -> WebhookConfig:
        return WebhookConfig(timeout_seconds=self.webhook_timeout_seconds)

    @property
    def outbox(self) -> OutboxConfig:
        return OutboxConfig(
            batch_size=self.outbox_batch_size,
            poll_interval_seconds=self.outbox_poll_interval_seconds,
            max_attempts=self.outbox_max_attempts,
            retry_base_delay_seconds=self.outbox_retry_base_delay_seconds,
            lease_seconds=self.outbox_lease_seconds,
            publish_timeout_seconds=self.outbox_publish_timeout_seconds,
        )
