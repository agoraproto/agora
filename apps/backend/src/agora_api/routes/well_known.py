"""Well-known endpoints (ADR 008).

/.well-known/agora.json publishes Agora's public webhook-signing key so
receivers can verify outbound webhooks. Receivers SHOULD cache for 24h.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..webhooks.signing import get_signer

router = APIRouter()


@router.get(
    "/.well-known/agora.json",
    summary="Public metadata for Agora — signing keys, supported events",
    tags=["well-known"],
)
async def agora_well_known() -> dict:
    signer = get_signer()
    return {
        "issuer": "agora",
        "signing_keys": [
            {
                "kid": signer.key_id,
                "alg": "Ed25519",
                "public_key_b64": signer.public_key_b64,
                "use": "webhook-sign",
            }
        ],
        "supported_events": [
            "job.offered",
            "job.accepted",
            "job.rejected",
            "job.result_submitted",
            "job.completed",
            "job.disputed",
            "job.resolved",
        ],
        "webhook_protocol_version": "1",
        "replay_window_seconds": 300,
        "max_attempts": 6,
    }
