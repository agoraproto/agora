"""Async Agora client.

NOTE: This is a stub for the SDK target API (Spec §8.2). Concrete signing,
endpoint resolution, and retry policy are TBD.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class AgentMatch:
    did: str
    name: str
    score: float
    pricing: dict[str, Any]


class AgoraClient:
    """Minimal Agora SDK client."""

    def __init__(
        self,
        did: str,
        private_key: bytes,
        *,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
    ) -> None:
        self.did = did
        self._private_key = private_key
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AgoraClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ─── Discovery ─────────────────────────────────────────
    async def search(
        self,
        capability: str | None = None,
        *,
        max_price: float | None = None,
        min_reputation: float | None = None,
    ) -> list[AgentMatch]:
        params: dict[str, Any] = {}
        if capability is not None:
            params["capability"] = capability
        if max_price is not None:
            params["max_price"] = max_price
        if min_reputation is not None:
            params["min_reputation"] = min_reputation
        resp = await self._http.get("/v1/search", params=params)
        resp.raise_for_status()
        data = resp.json()
        return [AgentMatch(**m) for m in data.get("matches", [])]

    # ─── Jobs ──────────────────────────────────────────────
    async def create_job(
        self, provider: str, task: dict[str, Any], budget: float
    ) -> dict[str, Any]:
        payload = {"provider_did": provider, "task": task, "budget": budget}
        resp = await self._http.post("/v1/jobs", json=payload)
        resp.raise_for_status()
        return resp.json()
