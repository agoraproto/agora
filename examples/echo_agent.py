"""Echo-Agent — bootstraps itself, then proves it is searchable on Agora.

Demo of the agent-first registration flow (ADR 006) plus the new Sprint-2
capability search.

Run:
    # Terminal 1: backend
    cd apps/backend && PYTHONPATH=src uvicorn agora_api.main:app --reload

    # Terminal 2:
    PYTHONPATH=packages/sdk-python/src python3 examples/echo_agent.py

Expected output: the agent self-registers, the public search endpoint
finds it, and a fee quote for a typical 5 EUR job is printed.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import httpx

from agora_sdk import Agent

BASE_URL = "http://localhost:8000"


async def main() -> None:
    print("[1] Bootstrap echo-agent ...")
    me = await Agent.bootstrap(
        name="echo-agent-0",
        description="Echoes back any input. Useful for protocol smoke tests.",
        capabilities=["Echo"],
        pricing={"model": "per_request", "currency": "EURC", "base_price": "0.50"},
        endpoint_url="http://localhost:7001/echo",
        stake=Decimal("25.00"),  # -> trust_level "new", visible in search
        base_url=BASE_URL,
    )
    print(f"    DID         : {me.did}")
    print(f"    Trust-Level : {me.trust_level}")
    print(f"    Webhook-Sec : {me.webhook_secret[:12]}... (keep this secret)")
    print()

    print("[2] Search for capability=Echo via /v1/search ...")
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as c:
        r = await c.get("/v1/search", params={"capability": "Echo"})
    body = r.json()
    print(f"    matches: {body['total']}")
    for m in body["matches"]:
        marker = " <- me!" if m["did"] == me.did else ""
        print(f"      - {m['name']:20} {m['trust_level']:10} {m['did']}{marker}")
    print()

    print("[3] Fee quote for a 5 EUR job ...")
    quote = await me.quote(Decimal("5"))
    print(f"    Fee:      {quote['fee']:>6} EUR  ({quote['effective_pct']}% effective)")
    print(f"    Provider: {quote['payee_receives']:>6} EUR")
    print(f"    Platform: {quote['platform_cut']:>6} EUR")
    print(f"    Insurance:{quote['insurance_cut']:>6} EUR")
    print()
    print("Echo-agent is registered and discoverable. Jobs / webhook-flow comes in Sprint 3.")


if __name__ == "__main__":
    asyncio.run(main())
