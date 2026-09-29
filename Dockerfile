FROM docker.io/library/python:3.14-slim AS base

ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV="/venv"

RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates; \
    rm -rf /var/lib/apt/lists/*

FROM base AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/venv \
    UV_PYTHON_DOWNLOADS=0

COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /uvx /usr/local/bin/

RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential; \
    rm -rf /var/lib/apt/lists/*; \
    uv venv /venv

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY README.md alembic.ini ./
COPY alembic ./alembic
COPY payflow ./payflow

RUN --mount=type=cache,target=/root/.cache/uv \
    uv build --wheel && \
    uv pip install --no-deps dist/*.whl

FROM base AS runtime

RUN useradd --system --no-create-home payflow

WORKDIR /app

COPY --from=build /venv /venv
COPY alembic.ini ./
COPY alembic ./alembic

USER payflow

EXPOSE 8000

CMD ["python", "-m", "payflow.presentation.api"]
