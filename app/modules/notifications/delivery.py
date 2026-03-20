from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(slots=True)
class DeliveryResult:
    success: bool
    response_status: int | None
    error_message: str | None


async def deliver_webhook(url: str, payload: dict, timeout_seconds: int) -> DeliveryResult:
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
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

