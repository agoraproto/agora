"""Buyer-Agent runtime loop.

Every `tick_seconds` it picks a random capability from its needs,
searches for a provider, hires via x402, waits for the result, then
approveAndPay. Stops when the wallet balance drops below a safety
threshold.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import sys
from decimal import Decimal
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))
from personalities import BUYERS

API = "https://api.agoraproto.org"
RPC = "https://sepolia.base.org"
USDC_DECIMALS = 6

log = logging.getLogger("swarm.buyer")


class Buyer:
    def __init__(self, slug: str, did: str, address: str, private_key: str) -> None:
        self.slug = slug
        self.did = did
        self.address = address
        self.private_key = private_key
        self.spec = next(b for b in BUYERS if b.slug == slug)
        self.pending_jobs: dict[str, dict] = {}  # job_id → {hired_at, provider_did, capability}

    async def run(self) -> None:
        log.info("[%s] starting (needs=%s tick=%ss)", self.slug, self.spec.needs, self.spec.tick_seconds)
        # Stagger startup so 10 buyers don't all hire in the same second
        await asyncio.sleep(random.uniform(0, 30))
        while True:
            try:
                await self._tick()
            except Exception as e:
                log.exception("[%s] tick failed: %s", self.slug, e)
            await asyncio.sleep(self.spec.tick_seconds)

    async def _tick(self) -> None:
        # First, try to approve any submitted jobs we're waiting on
        await self._check_pending()

        # Then maybe hire someone
        capability = random.choice(self.spec.needs)
        task_template = self.spec.task_templates.get(capability)
        if not task_template:
            return
        try:
            task = json.loads(task_template)
        except Exception:
            return

        # Find a listing offering this capability
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.get(f"{API}/v1/listings", params={"listing_type": "service"})
        listings = r.json().get("listings", [])
        matches = [L for L in listings if L.get("service_capability") == capability and L.get("status") == "active"]
        if not matches:
            log.info("[%s] no provider found for %s", self.slug, capability)
            return

        listing = random.choice(matches)
        provider_did = listing["seller_did"]
        if provider_did == self.did:
            return  # don't hire yourself

        log.info("[%s] hiring %s (%s) for %s USDC", self.slug, listing["title"], provider_did[:25], listing["price_amount"])

        # x402 hire via the SDK
        try:
            from agora_sdk.x402 import hire_with_x402
        except ImportError:
            log.error("agora_sdk not installed")
            return

        try:
            job = await hire_with_x402(
                API,
                requester_did=self.did,
                provider_did=provider_did,
                task=task,
                budget_usdc=str(listing["price_amount"]),
                rpc_url=RPC,
                private_key=self.private_key,
            )
            log.info("[%s] hired → job %s", self.slug, job.get("id"))
            self.pending_jobs[job["id"]] = {
                "provider_did": provider_did,
                "capability": capability,
                "listing_id": listing["id"],
            }
        except Exception as e:
            log.exception("[%s] hire failed: %s", self.slug, e)

    async def _check_pending(self) -> None:
        """For each job we hired, if the provider has submitted, approve+pay."""
        # Query the API for all submitted jobs where this buyer is the
        # requester. This is robust against process restarts (in-memory
        # pending_jobs is empty after a fresh start, but the chain knows).
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.get(
                f"{API}/v1/jobs",
                params={"requester_did": self.did, "status": "submitted"},
            )
        if r.status_code != 200:
            return
        jobs_data = r.json()
        jobs = jobs_data.get("jobs", jobs_data if isinstance(jobs_data, list) else [])

        async with httpx.AsyncClient(timeout=15) as http:
            for j in jobs:
                job_id = j.get("id")
                if not job_id:
                    continue
                # The search filter is unreliable — re-check status on the
                # full record before approving.
                rd = await http.get(f"{API}/v1/jobs/{job_id}")
                if rd.status_code != 200:
                    continue
                full = rd.json()
                if full.get("status") != "submitted":
                    continue
                log.info("[%s] approving submitted job %s", self.slug, job_id)
                try:
                    from agora_sdk.x402 import approve_with_x402
                    await approve_with_x402(
                        API,
                        job_id=job_id,
                        rpc_url=RPC,
                        private_key=self.private_key,
                    )
                    log.info("[%s] ✅ approved + paid for job %s", self.slug, job_id)
                    self.pending_jobs.pop(job_id, None)
                except Exception as e:
                    log.exception("[%s] approve failed: %s", self.slug, e)
