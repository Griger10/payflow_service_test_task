from uuid import UUID

import httpx
import pytest

from payflow.infra.integrations.webhook import DELIVERY_ID_HEADER, HttpxWebhookClient


@pytest.mark.asyncio
async def test_webhook_client_sends_stable_delivery_id_header() -> None:
    delivery_id = UUID("00000000-0000-0000-0000-000000000001")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = HttpxWebhookClient(http_client)
        await client.send(
            "https://client.example/hook", {"status": "succeeded"}, delivery_id=delivery_id
        )

    assert seen[0].headers[DELIVERY_ID_HEADER] == str(delivery_id)
