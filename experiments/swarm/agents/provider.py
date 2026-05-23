"""Provider-Agent runtime loop.

Polls the API for jobs assigned to this provider in status='offered',
runs the LLM, submits the result on-chain (submitResult + backend
mirror via x402). Each Provider instance owns one wallet + one DID.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.llm import ask
from personalities import PROVIDERS

API = "https://api.agoraproto.org"
RPC = "https://sepolia.base.org"
POLL_INTERVAL = 25  # seconds

log = logging.getLogger("swarm.provider")


class Provider:
    def __init__(self, slug: str, did: str, address: str, private_key: str) -> None:
        self.slug = slug
        self.did = did
        self.address = address
        self.private_key = private_key
        self.spec = next(p for p in PROVIDERS if p.slug == slug)
        self.handled: set[str] = set()

    async def run(self) -> None:
        log.info("[%s] starting (cap=%s, price=%s)", self.slug, self.spec.capability, self.spec.base_price_usdc)
        while True:
            try:
                await self._tick()
            except Exception as e:
                log.exception("[%s] tick failed: %s", self.slug, e)
            await asyncio.sleep(POLL_INTERVAL)

    async def _tick(self) -> None:
        # Find offered on-chain jobs where this provider is the recipient.
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.get(f"{API}/v1/jobs", params={"provider_did": self.did, "status": "offered"})
        if r.status_code != 200:
            return
        jobs = r.json().get("jobs", r.json() if isinstance(r.json(), list) else [])
        async with httpx.AsyncClient(timeout=20) as http:
            for job in jobs:
                jid = job.get("id")
                if not jid or jid in self.handled:
                    continue
                # The /v1/jobs search endpoint may omit settlement_mode and
                # task_spec — fetch the full job by id so handle_job has
                # everything it needs.
                rd = await http.get(f"{API}/v1/jobs/{jid}")
                if rd.status_code != 200:
                    continue
                full = rd.json()
                # Backend bug: /v1/jobs/{id} doesn't serialize
                # `settlement_mode`. For now we attempt handle_job on every
                # offered job — submit_result_with_x402 will 503 if it
                # turns out to be off-chain.
                await self._handle_job(full)
                self.handled.add(jid)

    async def _handle_job(self, job: dict) -> None:
        log.info("[%s] handling job %s", self.slug, job["id"])
        task_spec = job.get("task_spec", {})

        # Call LLM to produce the deliverable
        text = await ask(self.spec.system_prompt, task_spec)
        result_payload = {"text": text, "by": self.did, "capability": self.spec.capability}

        # Use the agora-sdk's x402 submit helper to drive submitResult on-chain.
        # We import locally so the swarm package doesn't fail at import time
        # if the SDK isn't yet installed in the runtime env.
        try:
            from agora_sdk.x402 import submit_result_with_x402
        except ImportError:
            log.error("agora_sdk not installed; install with: pip install -e packages/sdk-python")
            return

        try:
            result = await submit_result_with_x402(
                API,
                job_id=job["id"],
                result=result_payload,
                rpc_url=RPC,
                private_key=self.private_key,
            )
            log.info("[%s] submitResult OK: %s", self.slug, result.get("status"))
        except Exception as e:
            log.exception("[%s] submit_result failed: %s", self.slug, e)
