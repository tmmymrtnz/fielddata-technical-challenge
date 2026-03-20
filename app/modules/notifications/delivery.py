from __future__ import annotations

import asyncio
from dataclasses import dataclass
from weakref import WeakKeyDictionary

import httpx


@dataclass(slots=True)
class DeliveryResult:
    success: bool
    response_status: int | None
    error_message: str | None


_clients_by_loop: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[int, httpx.AsyncClient]] = WeakKeyDictionary()


async def _get_delivery_client(timeout_seconds: int) -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    clients_for_loop = _clients_by_loop.get(loop)
    if clients_for_loop is None:
        clients_for_loop = {}
        _clients_by_loop[loop] = clients_for_loop

    client = clients_for_loop.get(timeout_seconds)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=timeout_seconds)
        clients_for_loop[timeout_seconds] = client

    return client


async def close_delivery_clients() -> None:
    loop = asyncio.get_running_loop()
    clients_for_loop = _clients_by_loop.pop(loop, {})
    for client in clients_for_loop.values():
        await client.aclose()


async def deliver_webhook(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:
    try:
        client = await _get_delivery_client(timeout_seconds)
        response = await client.post(url, json=payload)
        if 200 <= response.status_code < 300:
            return DeliveryResult(success=True, response_status=response.status_code, error_message=None)
        return DeliveryResult(
            success=False,
            response_status=response.status_code,
            error_message=f"Webhook responded with status {response.status_code}",
        )
    except httpx.HTTPError as exc:
        return DeliveryResult(success=False, response_status=None, error_message=str(exc))
