# Payflow

Payflow — сервис асинхронного проведения платежей. HTTP API регистрирует платёж и возвращает управление с кодом `202`,
после чего отдельные процессы публикуют команду через transactional outbox, обрабатывают её в RabbitMQ consumer и
отправляют итоговый webhook.

Главная инженерная идея проекта: **не пытаться получить exactly-once доставку, а собрать «эффективно однократную»
обработку из at-least-once доставки и идемпотентных операций**. Решения описаны в разделе
[Проектные решения по надёжности](#проектные-решения-по-надёжности).

## Содержание

- [Что входит в решение](#что-входит-в-решение)
- [Слои](#слои)
- [Прохождение платежа](#прохождение-платежа)
- [Проектные решения по надёжности](#проектные-решения-по-надёжности)
- [Запуск](#запуск)
- [Конфигурация](#конфигурация)
- [HTTP API](#http-api)
- [Webhook](#webhook)
- [RabbitMQ](#rabbitmq)
- [Outbox](#outbox)
- [Запуск процессов без полного Compose](#запуск-процессов-без-полного-compose)
- [Миграции и проверки](#миграции-и-проверки)
- [Docker image](#docker-image)

## Что входит в решение

- FastAPI API с проверкой `X-API-Key`;
- защита создания платежа через `Idempotency-Key`;
- PostgreSQL и SQLAlchemy 2.1 в async-режиме;
- атомарная запись платежа и outbox-события;
- outbox relay с lease-арендой строк и публикацией вне транзакции;
- FastStream consumer поверх RabbitMQ;
- эмулятор шлюза: задержка 2–5 секунд, 90% успешных операций;
- три попытки обработки с экспоненциальной задержкой;
- Dead Letter Queue для исчерпанных сообщений;
- webhook с фиксацией успешной доставки и стабильным идентификатором доставки;
- Alembic-миграции и полное Docker Compose окружение.

## Слои

```text
payflow/
├── domain/                 # бизнес-сущности и enum, без внешних зависимостей
│   ├── payment.py
│   ├── outbox.py
│   └── enums.py
├── app/                    # сценарии и интерфейсы зависимостей
│   ├── dto.py
│   ├── errors.py
│   ├── interfaces/
│   └── services/
│       ├── create_payment.py
│       ├── get_payment.py
│       ├── process_payment.py
│       └── publish_outbox.py
├── infra/                  # технические реализации
│   ├── database/           # ORM, repositories, UoW, engine/session factory
│   ├── messaging/          # exchanges, queues и publishers
│   ├── integrations/       # webhook, gateway, clock и UUID
│   └── config.py
├── bootstrap/              # общая сборка: Resources и фабрики сервисов
│   ├── resources.py
│   └── factories.py
└── presentation/           # транспорт и исполняемые процессы
    ├── api/                # dependencies.py — провайдеры FastAPI Depends
    ├── consumer/           # dependencies.py — провайдеры FastStream Depends
    └── outbox/
```

Правило зависимостей:

```text
presentation ──> app <── infra
                  │        │
                  └─> domain <─┘
```

`domain` не импортирует другие слои. `app` знает только доменную модель и собственные интерфейсы. SQLAlchemy полностью
изолирован в `infra/database`; FastStream и RabbitMQ — в `infra/messaging`. `bootstrap` собирает объекты из `app` и
`infra`, но не знает о фреймворках. Границы слоёв проверяет `tests/unit/test_package_boundaries.py`.

### Внедрение зависимостей

Сервисы получают зависимости через конструктор и знают только `Protocol`-интерфейсы из `app/interfaces`. Сборкой
занимаются три части:

- `bootstrap/resources.py` — `open_resources()` создаёт долгоживущие `Resources` (настройки, engine, session factory) и
  закрывает engine при остановке;
- `bootstrap/factories.py` — функции `make_*`, единственное место, где сервисы соединяются с реализациями;
- провайдеры фреймворков — тонкие обёртки над фабриками, объявленные в сигнатурах обработчиков через `Depends`.

| Процесс | Ресурсы | Провайдеры |
|---|---|---|
| API | lifespan создаёт `Resources` и отдаёт их в состояние lifespan | `presentation/api/dependencies.py`, FastAPI `Depends`; цепочка `get_resources → get_settings / get_uow_factory → get_create_payment` |
| Consumer | lifespan создаёт `Resources` и один `httpx.AsyncClient`, кладёт их в контекст FastStream | `presentation/consumer/dependencies.py`, `faststream.Depends` и `Context` |
| Outbox relay | `open_resources()` в `run()` | без фреймворка: `make_publish_outbox` вызывается напрямую |

В тестах зависимость подменяется без пересборки приложения: `app.dependency_overrides[get_clock] = ...` в API и
`dependency_provider.override(get_process_payment, ...)` в consumer (см. `tests/service`). Приложения создаются
фабриками `create_app()` и `create_worker()`, при импорте модулей engine и брокер не создаются.

Сервис состоит из трёх независимо масштабируемых процессов (`api`, `outbox`, `consumer`), которые общаются только через
PostgreSQL и RabbitMQ и не разделяют состояние в памяти.

## Прохождение платежа

1. `POST /api/v1/payments` принимает данные и обязательный idempotency key.
2. `CreatePayment` записывает `payments` и `outbox` в одной транзакции.
3. Outbox process забирает готовые строки с lease через `FOR UPDATE SKIP LOCKED` и публикует их вне транзакции.
4. Событие публикуется с routing key `payments.new`.
5. Consumer блокирует платёж, вызывает gateway emulator и сохраняет итоговый статус.
6. Consumer отправляет webhook вне транзакции, затем фиксирует доставку.
7. Ошибка обработки направляет сообщение в retry queue; последняя ошибка — в DLQ.

```mermaid
sequenceDiagram
    participant C as Клиент
    participant A as API
    participant DB as PostgreSQL
    participant R as Outbox relay
    participant MQ as RabbitMQ
    participant W as Consumer
    participant M as Webhook получателя
    C ->> A: POST /payments + Idempotency-Key
    A ->> DB: TX: INSERT payment + INSERT outbox
    A -->> C: 202 Accepted
    loop poll
        R ->> DB: TX: claim (SKIP LOCKED, locked_until)
        R ->> MQ: publish (message_id = event id)
        R ->> DB: TX: mark published / retry / failed
    end
    MQ ->> W: payments.new
    W ->> DB: TX: FOR UPDATE, gateway, save status
    W ->> M: POST + X-Payflow-Delivery-Id
    W ->> DB: TX: mark webhook delivered
    W ->> MQ: ack
```

## Проектные решения по надёжности

Подходы взяты из книги Мартина Клеппмана *Designing Data-Intensive Applications*.

| Проблема | Решение |
|---|---|
| Нельзя атомарно записать в БД и брокер | Transactional outbox: платёж и событие пишутся одной транзакцией, отдельный relay публикует их в брокер. Проще 2PC и CDC, но задержка определяется polling |
| Повторы доставки неизбежны | At-least-once на каждом звене, дубли гасятся идемпотентной обработкой |
| Транспорт не защищает от повторов выше по стеку | Сквозные идентификаторы: `Idempotency-Key` (уникальный индекс + `INSERT … ON CONFLICT DO NOTHING`), `message_id` = `outbox.id`, `X-Payflow-Delivery-Id` = `payment_id` |
| Долгие блокировки на время сетевых вызовов | Relay забирает строки с lease (`locked_until`), публикует и вебхук шлёт вне транзакций. Просроченный lease даёт дубль, а не порчу данных |
| Параллельная обработка одного платежа | `FOR UPDATE` по платежу; вызов шлюза остаётся под ним, потому что списание не идемпотентно |
| Порядок сообщений при нескольких потребителях | Не гарантируется: `payment.created` его не требует |

Повторы идут с exponential backoff: relay хранит задержку в `next_attempt_at`, consumer — в TTL retry-очередей. Исчерпанные попытки не теряются: `failed` в outbox, DLQ в RabbitMQ.

`OUTBOX_LEASE_SECONDS` должен превышать время публикации батча (`OUTBOX_BATCH_SIZE × OUTBOX_PUBLISH_TIMEOUT_SECONDS` в худшем случае), иначе растёт число дублей.

**Ограничения:** нет дедупликации по `message_id` в consumer; нет retention `published` и переобработки `failed` в outbox; webhook может уйти дважды (получатель дедуплицирует по `X-Payflow-Delivery-Id`); порядок событий не гарантирован; все ошибки consumer уходят в retry без разбора.

## Запуск

Создайте локальный файл настроек и поднимите окружение:

```bash
cp .env.example .env
docker compose up --build
```

Доступные адреса:

| Компонент           | Адрес                          |
|---------------------|--------------------------------|
| API                 | `http://127.0.0.1:8000`        |
| Healthcheck         | `http://127.0.0.1:8000/health` |
| RabbitMQ Management | `http://127.0.0.1:15672`       |

RabbitMQ использует `guest` / `guest` по умолчанию.

Compose запускает `postgres`, `rabbitmq`, одноразовый `migrator`, а затем `api`, `outbox` и `consumer`. Команда запуска
API задана один раз, в `CMD` Dockerfile; остальные сервисы переопределяют её в `docker-compose.yml`.

## Конфигурация

| Переменная                        |                                        `.env.example` / Compose | Назначение                                    |
|-----------------------------------|----------------------------------------------------------------:|-----------------------------------------------|
| `API_KEY`                         |                                                `secret-api-key` | ключ доступа к payment API                    |
| `DATABASE_URL`                    | `postgresql+asyncpg://postgres:postgres@postgres:5432/payments` | PostgreSQL DSN                                |
| `RABBITMQ_URL`                    |                             `amqp://guest:guest@rabbitmq:5672/` | RabbitMQ DSN                                  |
| `PAYMENT_SUCCESS_RATE`            |                                                           `0.9` | вероятность успеха gateway                    |
| `PAYMENT_MIN_DELAY_SECONDS`       |                                                             `2` | нижняя граница задержки                       |
| `PAYMENT_MAX_DELAY_SECONDS`       |                                                             `5` | верхняя граница задержки                      |
| `RETRY_MAX_ATTEMPTS`              |                                                             `3` | общее число попыток сообщения                 |
| `RETRY_BASE_DELAY_SECONDS`        |                                                             `1` | база exponential backoff                      |
| `WEBHOOK_TIMEOUT_SECONDS`         |                                                             `5` | таймаут webhook-запроса                       |
| `OUTBOX_BATCH_SIZE`               |                                                            `50` | событий за проход relay                       |
| `OUTBOX_POLL_INTERVAL_SECONDS`    |                                                             `1` | пауза между проходами                         |
| `OUTBOX_MAX_ATTEMPTS`             |                                                            `10` | лимит публикации события                      |
| `OUTBOX_RETRY_BASE_DELAY_SECONDS` |                                                             `1` | база outbox backoff                           |
| `OUTBOX_LEASE_SECONDS`            |                                                            `60` | на сколько relay «арендует» забранные события |
| `OUTBOX_PUBLISH_TIMEOUT_SECONDS`  |                                                            `10` | таймаут публикации одного события             |

В коде переменные собираются в `ServiceConfig`, затем преобразуются в узкие секции `api`, `database`, `broker`,
`processing`, `webhook` и `outbox`.

Встроенные значения `ServiceConfig` используют `localhost` для PostgreSQL и RabbitMQ; `.env.example` переключает
hostnames на Compose-сервисы `postgres` и `rabbitmq`.

## HTTP API

Payment endpoints требуют заголовок:

```http
X-API-Key: secret-api-key
```

### Регистрация платежа

```http
POST /api/v1/payments
Content-Type: application/json
X-API-Key: secret-api-key
Idempotency-Key: invoice-741-attempt-1
```

```json
{
  "amount": "1490.00",
  "currency": "RUB",
  "description": "Invoice 741",
  "metadata": {
    "invoice_id": "741",
    "source": "checkout"
  },
  "webhook_url": "https://merchant.example/payment-events"
}
```

Ответ — `202 Accepted`:

```json
{
  "payment_id": "32f43e7b-aa4c-459d-bb62-a61e3ace54ba",
  "status": "pending",
  "created_at": "2026-08-04T10:30:00Z"
}
```

Повтор идентичного запроса с тем же `Idempotency-Key` возвращает исходный платёж. Другой payload с занятым ключом
возвращает `409 Conflict`.

### Состояние платежа

```http
GET /api/v1/payments/32f43e7b-aa4c-459d-bb62-a61e3ace54ba
X-API-Key: secret-api-key
```

```json
{
  "payment_id": "32f43e7b-aa4c-459d-bb62-a61e3ace54ba",
  "amount": "1490.00",
  "currency": "RUB",
  "description": "Invoice 741",
  "metadata": {
    "invoice_id": "741",
    "source": "checkout"
  },
  "status": "succeeded",
  "idempotency_key": "invoice-741-attempt-1",
  "webhook_url": "https://merchant.example/payment-events",
  "created_at": "2026-08-04T10:30:00Z",
  "processed_at": "2026-08-04T10:30:03Z"
}
```

Возможные ответы: `200`, `202`, `401`, `404`, `409`, `422`.

## Webhook

Consumer выполняет `POST` по URL платежа:

```json
{
  "payment_id": "32f43e7b-aa4c-459d-bb62-a61e3ace54ba",
  "status": "succeeded",
  "amount": "1490.00",
  "currency": "RUB",
  "processed_at": "2026-08-04T10:30:03+00:00",
  "metadata": {
    "invoice_id": "741",
    "source": "checkout"
  }
}
```

Запрос содержит заголовок `X-Payflow-Delivery-Id` (равен `payment_id`), значение стабильно между повторами. Запрос
отправляется без открытой транзакции и без блокировки строки платежа. Если consumer упал после отправки, но до отметки
доставки, или два consumer обработали одно сообщение параллельно, вебхук уйдёт повторно, поэтому получатель должен
дедуплицировать по этому заголовку.

После ответа `2xx` таблица `webhook_deliveries` получает отметку доставки. Повторно полученное broker-сообщение
проверяет эту отметку перед отправкой.

Рекомендация получателю: хранить обработанные `X-Payflow-Delivery-Id` и отвечать `2xx` на повтор, не выполняя
бизнес-действие второй раз (см. [Проектные решения по надёжности](#проектные-решения-по-надёжности)).

## RabbitMQ

| Тип             | Имя                    | Роль                               |
|-----------------|------------------------|------------------------------------|
| Direct exchange | `payments`             | основные события                   |
| Queue           | `payments.new`         | новые платежи                      |
| Retry queues    | `payments.new.retry.N` | TTL-задержка попытки               |
| DLX             | `payments.dlx`         | маршрутизация окончательных ошибок |
| DLQ             | `payments.new.dlq`     | сообщения после последней попытки  |

Retry delay вычисляется как `RETRY_BASE_DELAY_SECONDS * 2^(N - 1)`. Retry queue после TTL возвращает сообщение в
`payments.new`. Третья неуспешная обработка отклоняет сообщение без requeue, после чего RabbitMQ направляет его в DLQ.

Сообщения публикуются как persistent, подтверждение (`ack`) consumer отправляет вручную только после завершения
обработки или постановки в retry.

## Outbox

Запись платежа и события происходит одной транзакцией. Relay работает в три шага:

1. Короткая транзакция «забирает» готовые строки (`pending`, наступивший `next_attempt_at`, `locked_until` пуст или
   истёк) через `FOR UPDATE SKIP LOCKED` и выставляет `locked_until = now + OUTBOX_LEASE_SECONDS`.
2. Публикация в RabbitMQ идёт без открытой транзакции и блокировок, с таймаутом `OUTBOX_PUBLISH_TIMEOUT_SECONDS`.
3. Результат фиксируется отдельной короткой транзакцией: `published`, либо увеличение `attempts` с exponential retry.
   После `OUTBOX_MAX_ATTEMPTS` строка получает статус `failed`. Во всех случаях `locked_until` сбрасывается.

Если relay падает между публикацией и фиксацией результата, lease истекает и событие публикуется повторно. Гарантия
доставки — at-least-once, `message_id` события стабилен.

Состояния строки outbox:

```mermaid
stateDiagram-v2
    [*] --> pending: запись в одной транзакции с платежом
    pending --> leased: claim (locked_until = now + lease)
    leased --> published: успешная публикация
    leased --> pending: ошибка, attempts < max (backoff, lease сброшен)
    leased --> failed: ошибка, attempts >= max
    leased --> pending: lease истёк без результата (повторный claim)
```

`leased` — не отдельный статус в БД, а `status = pending` с `locked_until` в будущем.

## Запуск процессов без полного Compose

```bash
uv sync --locked
docker compose up -d postgres rabbitmq
uv run --python 3.14 alembic upgrade head
```

В отдельных терминалах:

```bash
uv run --python 3.14 python -m payflow.presentation.api
uv run --python 3.14 python -m payflow.presentation.outbox
uv run --python 3.14 python -m payflow.presentation.consumer
```

При запуске вне Docker задайте `DATABASE_URL` и `RABBITMQ_URL` с `localhost` вместо Compose hostnames.

## Миграции и проверки

Все проверки одной командой (нужен [just](https://github.com/casey/just) и запущенный Postgres, его поднимает `just db`):

```bash
just db      # Postgres для тестов
just check   # ruff format --check, ruff check, mypy (strict), pytest
just fix     # автоформатирование и безопасные правки линтера
```

По отдельности:

```bash
uv run --python 3.14 alembic upgrade head
uv run --python 3.14 pytest tests -q
uv run --python 3.14 ruff format --check .
uv run --python 3.14 ruff check .
uv run --python 3.14 mypy
docker compose config --quiet
docker compose build
```

Статическая типизация настроена в `mypy.ini` (`strict = True`, плагин `pydantic.mypy`) и проверяет `payflow`, `tests` и `alembic`.

Что дополнительно проверяется сверх `strict`:

- `payflow.domain` и `payflow.application` без единого явного `Any` (`disallow_any_explicit`); JSON-данные типизируются рекурсивным `JsonValue` / `JsonObject` из `payflow/domain/types.py`, а ruff запрещает голый `Any` (`ANN401`);
- реализации интерфейсов явно наследуют `Protocol` и помечены `@override` (`explicit-override`), поэтому расхождение сигнатуры видно в самом классе;
- ORM возвращает enum'ы (`StrEnumType` в `infra/database/types.py`), в БД остаётся `VARCHAR`, миграции не нужны;
- константы объявлены `Final`.

`@runtime_checkable` не используется: он проверяет только наличие методов, а не сигнатуры и `async`, и создаёт ложное чувство проверки. Соответствие интерфейсам гарантирует mypy.

Интеграционные тесты читают `TEST_DATABASE_URL`. Если переменная не задана, используется
`postgresql+asyncpg://postgres:postgres@localhost:5432/payments`.

Что покрыто тестами надёжности:

- claim строк outbox: пропуск арендованных строк, повторный захват после истечения lease, непересекающиеся выборки
  параллельных relay;
- relay: успех, retry с backoff, переход в `failed`, таймаут публикации, публикация без блокировки строки;
- consumer: повторная обработка без повторного списания, стабильный `delivery_id`, отправка webhook без блокировки
  строки платежа.

## Docker image

```bash
docker build -t payflow:local .
```

Образ собирается в несколько стадий, устанавливает lock-зависимости и запускает приложение от системного пользователя
`payflow`.
