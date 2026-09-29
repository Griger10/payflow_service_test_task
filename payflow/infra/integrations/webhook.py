from collections.abc import Mapping
from typing import Final, override
from uuid import UUID

import httpx

from payflow.application.interfaces import WebhookClient
from payflow.domain import JsonValue

DELIVERY_ID_HEADER: Final = "X-Payflow-Delivery-Id"


class HttpxWebhookClient(WebhookClient):
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @override
    async def send(self, url: str, payload: Mapping[str, JsonValue], *, delivery_id: UUID) -> None:
        response = await self._client.post(
            url, json=dict(payload), headers={DELIVERY_ID_HEADER: str(delivery_id)}
        )
        response.raise_for_status()
