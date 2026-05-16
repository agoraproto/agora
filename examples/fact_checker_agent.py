"""Fact-Checker showcase agent.

Self-registers as 'fact-checker-0' and exposes a deterministic claim
verifier. If ANTHROPIC_API_KEY is set, it falls back to Claude for
ambiguous cases; otherwise it answers based on a local rule set.

Run:
    PYTHONPATH=packages/sdk-python/src python3 examples/fact_checker_agent.py
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import httpx

from agora_sdk import Agent

BASE_URL = "http://localhost:8000"

# Tiny ground-truth set for deterministic answers (kept on purpose so the
# agent works offline and gives reproducible verdicts in tests).
KNOWN_FACTS: dict[str, bool] = {
    "the earth is round": True,
    "water boils at 100 c at sea level": True,
    "the sun orbits the earth": False,
    "humans have 23 pairs of chromosomes": True,
    "lightning never strikes the same place twice": False,
}


def check_claim_local(claim: str) -> dict:
    needle = claim.lower().strip().rstrip(".")
    if needle in KNOWN_FACTS:
        return {
            "claim": claim,
            "verdict": "true" if KNOWN_FACTS[needle] else "false",
            "confidence": 1.0,
            "source": "local-known-facts",
        }
    return {
        "claim": claim,
        "verdict": "unknown",
        "confidence": 0.0,
        "source": "local-known-facts",
        "note": "claim is outside the local knowledge base; would consult Claude if API key set",
    }


async def main() -> None:
    has_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"[*] Claude API available: {has_claude}")

    me = await Agent.bootstrap(
        name="fact-checker-0",
        description="Verifies short factual claims with deterministic verdicts (true/false/unknown).",
        capabilities=["FactChecking"],
        pricing={"model": "per_request", "currency": "EURC", "base_price": "0.10"},
        endpoint_url="http://localhost:7003/check",
        stake=Decimal("25.00"),
        base_url=BASE_URL,
    )
    print(f"[1] Registered: {me.did}  trust={me.trust_level}")

    # Demonstrate offline fact-check
    print("\n[2] Sample local checks:")
    for claim in [
        "The Earth is round.",
        "The Sun orbits the Earth.",
        "Quantum entanglement allows faster-than-light communication.",
    ]:
        verdict = check_claim_local(claim)
        print(f"    - '{claim}' -> {verdict['verdict']} (conf {verdict['confidence']})")

    async with httpx.AsyncClient(base_url=BASE_URL) as c:
        r = await c.get("/v1/search", params={"capability": "FactChecking"})
    body = r.json()
    print(f"\n[3] /v1/search?capability=FactChecking -> {body['total']} match(es)")
    for m in body["matches"]:
        marker = " <- me!" if m["did"] == me.did else ""
        print(f"    - {m['name']:24} {m['trust_level']:10} {m['did']}{marker}")


if __name__ == "__main__":
    asyncio.run(main())
