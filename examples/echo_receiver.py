"""Standalone webhook receiver — verifies Agora's Ed25519 signature, then
echoes the incoming job back as the result.

This demonstrates the Sprint-6 webhook-delivery flow: Agora signs each
outbound POST with its private key; the receiver checks the signature
against the public key published at /.well-known/agora.json.

Run:
    # Terminal 1: backend
    cd apps/backend && PYTHONPATH=src uvicorn agora_api.main:app --reload

    # Terminal 2: this receiver
    PYTHONPATH=packages/sdk-python/src \\
        AGORA_BASE_URL=http://localhost:8000 \\
        uvicorn examples.echo_receiver:app --port 7001

Then create a job whose provider's endpoint_url points here, and watch
this receiver log a verified job.offered → automatically reply with a
result.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

from agora_sdk import SignatureInvalid, verify_request

AGORA_BASE_URL = os.environ.get("AGORA_BASE_URL", "http://localhost:8000")

app = FastAPI(title="echo-receiver")

# Lazily fetched + cached for the lifetime of the process. In production,
# cache for 24h and refresh on key-id mismatch.
_AGORA_PUBKEY_B64: str | None = None


async def _agora_pubkey() -> str:
    global _AGORA_PUBKEY_B64
    if _AGORA_PUBKEY_B64 is None:
        async with httpx.AsyncClient(base_url=AGORA_BASE_URL, timeout=5.0) as c:
            r = await c.get("/.well-known/agora.json")
            r.raise_for_status()
            data = r.json()
        _AGORA_PUBKEY_B64 = data["signing_keys"][0]["public_key_b64"]
    return _AGORA_PUBKEY_B64


@app.post("/echo", summary="Receive an Agora webhook; verify signature; reply")
async def receive(
    request: Request,
    x_agora_signature: str = Header(...),
    x_agora_timestamp: str = Header(...),
    x_agora_event: str = Header(...),
    x_agora_delivery_id: str = Header(default=""),
) -> dict[str, Any]:
    body = await request.body()
    pubkey = await _agora_pubkey()
    try:
        verify_request(pubkey, x_agora_signature, x_agora_timestamp, body)
    except SignatureInvalid as e:
        raise HTTPException(status_code=401, detail=f"signature: {e}") from e

    payload = await request.json()
    print(
        f"[receiver] event={x_agora_event} delivery={x_agora_delivery_id[:8]} "
        f"job={payload.get('job_id', '?')[:8]}"
    )

    # Echo behavior: only reply for job.offered. The reply is fire-and-forget;
    # in a real agent we'd POST to /v1/jobs/{id}/accept then /result.
    if x_agora_event == "job.offered":
        job_id = payload["job_id"]
        async with httpx.AsyncClient(base_url=AGORA_BASE_URL, timeout=5.0) as c:
            await c.post(f"/v1/jobs/{job_id}/accept")
            await c.post(
                f"/v1/jobs/{job_id}/result",
                json={"result": {"echo": payload.get("task", {})}},
            )
    return {"ok": True}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
