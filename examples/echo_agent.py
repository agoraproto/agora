"""Echo-Agent — der erste sich-selbst-registrierende Agent auf Agora.

Demo der Agent-First-Architektur (ADR 006). Macht alles selbst:
  1. generiert eigenes Schlüsselpaar und DID
  2. registriert sich auf Agora (POST /v1/agents/register)
  3. (in Sprint 2+) wird via /v1/search auffindbar
  4. (Webhook-Server folgt in Sprint 3, sobald Job-Endpunkte stehen)

Run:
    # In einem Terminal: Agora-Backend starten
    cd apps/backend && PYTHONPATH=src uvicorn agora_api.main:app --reload

    # In einem zweiten Terminal:
    PYTHONPATH=packages/sdk-python/src python3 examples/echo_agent.py
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from agora_sdk import Agent


async def main() -> None:
    print("Bootstrap Echo-Agent ...")
    me = await Agent.bootstrap(
        name="echo-agent-0",
        description="Echoes back any input. Useful for protocol smoke tests.",
        capabilities=["Echo"],
        pricing={
            "model": "per_request",
            "currency": "EURC",
            "base_price": "0.50",
        },
        endpoint_url="http://localhost:7001/echo",
        stake=Decimal("5.00"),
    )

    print()
    print(f"  DID            : {me.did}")
    print(f"  Trust-Level    : {me.trust_level}")
    print(f"  Webhook-Secret : {me.webhook_secret[:12]}...")
    print()
    print("Agent registriert. Quote-Test fuer 100 EUR Auftrag:")

    quote = await me.quote(Decimal("100"))
    print(
        f"  Fee={quote['fee']} EUR  ({quote['effective_pct']}%)  "
        f"Payee bekommt {quote['payee_receives']} EUR"
    )


if __name__ == "__main__":
    asyncio.run(main())
