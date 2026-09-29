from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypedDict

from fastapi import FastAPI

from payflow.bootstrap.resources import Resources, open_resources
from payflow.infra.config import ServiceConfig
from payflow.presentation.api.routes import router as payments_router


class LifespanState(TypedDict):
    resources: Resources


def create_app(settings: ServiceConfig | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[LifespanState]:
        del app
        async with open_resources(settings) as resources:
            yield {"resources": resources}

    app = FastAPI(title="payflow", version="0.1.0", lifespan=lifespan)
    app.include_router(payments_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
