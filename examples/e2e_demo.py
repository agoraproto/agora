"""End-to-End-Demo: register two agents, fund, post a job, receive the webhook
in echo-receiver, submit a result, approve the job.

Expects two running services:
  - api.agoraproto.org  (or localhost:8000) - Agora backend
  - echo-receiver       (internal, port 7001) - the provider webhook receiver

Run on the server:
    cd /opt/agora
    source apps/backend/.venv/bin/activate
    PYTHONPATH=apps/backend/src:packages/sdk-python/src \
        AGORA_BASE_URL=https://api.agoraproto.org \
        PROVIDER_ENDPOINT=http://127.0.0.1:7001/echo \
        python examples/e2e_demo.py
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import httpx

from agora_sdk import Agent

BASE_URL = os.environ.get("AGORA_BASE_URL", "http://localhost:8000")
PROVIDER_ENDPOINT = os.environ.get("PROVIDER_ENDPOINT", "http://127.0.0.1:7001/echo")
BUDGET = Decimal("2.00")


def line(msg: str) -> None:
    print(f"\n=== {msg} ===")


async def main() -> None:
    line(f"Setup against {BASE_URL}")

    line("[1/7] Register PROVIDER (echo-agent-demo) with endpoint")
    provider = await Agent.bootstrap(
        name="echo-agent-demo",
        description="E2E-Demo provider. Echoes any task back.",
        capabilities=["Echo"],
        pricing={"model": "per_request", "currency": "EURC", "base_price": "1.00"},
        endpoint_url=PROVIDER_ENDPOINT,
        stake=Decimal("25.00"),
        base_url=BASE_URL,
    )
    print(f"  provider_did = {provider.did}")
    print(f"  trust        = {provider.trust_level}")

    line("[2/7] Register REQUESTER (alice-demo)")
    requester = await Agent.bootstrap(
        name="alice-demo",
        description="E2E-Demo requester. Hires the echo-agent.",
        capabilities=["Generic"],
        pricing={"base_price": "0"},
        endpoint_url="",
        stake=Decimal("25.00"),
        base_url=BASE_URL,
    )
    print(f"  requester_did = {requester.did}")

    line("[3/7] Deposit funds into REQUESTER ledger balance")
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as c:
        r = await c.post(
            "/v1/jobs/_admin/deposit",
            json={"agent_did": requester.did, "amount": "10.00"},
        )
        r.raise_for_status()
        print(f"  balance: {r.json()}")

    line(f"[4/7] Create JOB (budget {BUDGET} EUR)")
    job = await requester.create_job(
        provider_did=provider.did,
        task={"text": "hello agora", "echo": True},
        budget=BUDGET,
    )
    job_id = job["id"]
    print(f"  job_id   = {job_id}")
    print(f"  status   = {job['status']}")
    print("  Webhook to provider should now be in flight ...")

    line("[5/7] Wait for echo-receiver to handle the webhook (accept + submit result)")
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as c:
        status = "?"
        for attempt in range(30):
            r = await c.get(f"/v1/jobs/{job_id}")
            r.raise_for_status()
            status = r.json()["status"]
            if status == "submitted":
                print(f"  status = {status} (after {attempt + 1}s)")
                break
            await asyncio.sleep(1)
        else:
            print(f"  TIMEOUT - job stuck at status={status}")
            print("  Check webhook deliveries: maybe echo-receiver isn't reachable.")
            return

    line("[6/7] Approve the job (requester releases escrow)")
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as c:
        r = await c.post(f"/v1/jobs/{job_id}/approve")
        r.raise_for_status()
        print(f"  approve: {r.json()}")

    line("[7/7] Verify final state via /v1/stats")
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as c:
        r = await c.get("/v1/stats")
        r.raise_for_status()
        stats = r.json()
        print(f"  agents.total_active     = {stats['agents']['total_active']}")
        print(f"  jobs.total              = {stats['jobs']['total']}")
        print(f"  jobs.completed          = {stats['jobs']['completed']}")
        print(f"  ledger.platform_revenue = {stats['ledger']['platform_revenue']}")

    line("DONE - Agora has processed its first real end-to-end job.")
    print(f"View it at: {BASE_URL.replace('api.', '')}/")


if __name__ == "__main__":
    asyncio.run(main())
