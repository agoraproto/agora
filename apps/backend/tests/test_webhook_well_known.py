"""Public well-known endpoint exposes the signing pubkey."""

from __future__ import annotations

import base64

import pytest


@pytest.mark.asyncio
async def test_well_known_endpoint(client) -> None:
    r = await client.get("/.well-known/agora.json")
    assert r.status_code == 200
    data = r.json()
    assert data["issuer"] == "agora"
    assert data["webhook_protocol_version"] == "1"
    assert data["max_attempts"] >= 1

    keys = data["signing_keys"]
    assert len(keys) == 1
    assert keys[0]["alg"] == "Ed25519"
    # public key is base64-encoded 32 bytes
    raw = base64.b64decode(keys[0]["public_key_b64"])
    assert len(raw) == 32

    events = data["supported_events"]
    assert "job.offered" in events
    assert "job.completed" in events
    assert "job.disputed" in events
