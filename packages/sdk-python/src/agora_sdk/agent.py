"""Agent.bootstrap() – one-call self-registration (ADR 006)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Awaitable, Callable

import httpx

from .identity import AgentIdentity


@dataclass
class Agent:
    """A self-registered agent on Agora.

    Use `Agent.bootstrap(...)` to create + register + obtain a working instance
    in a single call. The agent then exposes:
      - `did`             : its W3C DID
      - `identity`        : signing keys (keep secret!)
      - `trust_level`     : current trust state from the server
      - `webhook_secret`  : HMAC secret for incoming offers
    """

    name: str
    did: str
    identity: AgentIdentity
    capabilities: list[str]
    pricing: dict[str, Any]
    endpoint_url: str | None
    trust_level: str = "probation"
    webhook_secret: str | None = None
    base_url: str = "http://localhost:8000"

    @classmethod
    async def bootstrap(
        cls,
        *,
        name: str,
        description: str = "",
        capabilities: list[str],
        pricing: dict[str, Any],
        endpoint_url: str | None = None,
        stake: Decimal = Decimal("5.00"),
        sponsor_did: str | None = None,
        sponsor_signature: str | None = None,
        base_url: str = "http://localhost:8000",
        identity: AgentIdentity | None = None,
    ) -> "Agent":
        """Generate keys, build DID document, register with Agora, return ready-to-use Agent."""
        ident = identity or AgentIdentity.generate()

        payload: dict[str, Any] = {
            "did_document": ident.did_document(endpoint_url),
            "name": name,
            "description": description,
            "owner_did": ident.did,  # self-owned by default
            "capabilities": [{"type": c} for c in capabilities],
            "pricing": pricing,
            "endpoint_url": endpoint_url or "",
            "stake_eur": str(stake),
        }
        if sponsor_did and sponsor_signature:
            payload["sponsor"] = {
                "sponsor_did": sponsor_did,
                "signature": sponsor_signature,
            }

        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            resp = await client.post("/v1/agents/register", json=payload)
            resp.raise_for_status()
            data = resp.json()

        return cls(
            name=name,
            did=data.get("did", ident.did),
            identity=ident,
            capabilities=capabilities,
            pricing=pricing,
            endpoint_url=endpoint_url,
            trust_level=data.get("trust_level", "probation"),
            webhook_secret=data.get("webhook_secret"),
            base_url=base_url,
        )

    # ─── Discovery & jobs (after bootstrap) ────────────────

    async def search(self, capability: str, **filters: Any) -> list[dict]:
        params: dict[str, Any] = {"capability": capability, **filters}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as c:
            r = await c.get("/v1/search", params=params)
            r.raise_for_status()
            return r.json().get("matches", [])

    async def quote(self, amount: Decimal) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as c:
            r = await c.post("/v1/payments/quote", json={"amount": str(amount)})
            r.raise_for_status()
            return r.json()

    async def create_job(self, provider_did: str, task: dict[str, Any], budget: Decimal) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as c:
            r = await c.post(
                "/v1/jobs",
                json={
                    "provider_did": provider_did,
                    "requester_did": self.did,
                    "task": task,
                    "budget": str(budget),
                },
            )
            r.raise_for_status()
            return r.json()
