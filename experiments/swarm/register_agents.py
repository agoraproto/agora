"""One-shot bootstrap: register all 20 agents on Agora + publish provider listings.

Run once after wallets are funded. Idempotent — agents that already
exist are silently skipped.
"""

from __future__ import annotations

import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

sys.path.insert(0, str(Path(__file__).parent))
from personalities import BUYERS, PROVIDERS

API = "https://api.agoraproto.org"
WALLETS_FILE = Path(__file__).parent / "data" / "wallets.json"


def make_did_document(addr: str) -> dict:
    """Minimal DID document — Sprint 9 ed25519 sponsor isn't used here.
    The agent self-registers with its EVM address as both ID + controller.
    """
    return {
        "id": f"did:agora:swarm-{addr[2:18].lower()}",
        "verificationMethod": [
            {
                "id": f"did:agora:swarm-{addr[2:18].lower()}#evm",
                "type": "EcdsaSecp256k1RecoveryMethod2020",
                "controller": f"did:agora:swarm-{addr[2:18].lower()}",
                "blockchainAccountId": f"eip155:84532:{addr}",
            }
        ],
        "service": [],
    }


def register_agent(slug: str, role: str, addr: str, pk: str) -> str | None:
    """Register an agent. Returns the assigned DID, or None on conflict."""
    did_doc = make_did_document(addr)
    did = did_doc["id"]

    if role == "provider":
        spec = next(p for p in PROVIDERS if p.slug == slug)
        body = {
            "did_document": did_doc,
            "name": spec.name,
            "description": spec.description,
            "owner_did": did,
            "capabilities": [{"type": spec.capability}],
            "pricing": {
                "model": "per_request",
                "currency": "USDC",
                "base_price": str(spec.base_price_usdc),
            },
            "endpoint_url": "",  # poll-based, no webhook needed
            "stake_eur": "25.00",
        }
    else:
        spec = next(b for b in BUYERS if b.slug == slug)
        body = {
            "did_document": did_doc,
            "name": spec.name,
            "description": spec.description,
            "owner_did": did,
            "capabilities": [],
            "pricing": {},
            "endpoint_url": "",
            "stake_eur": "25.00",
        }

    r = httpx.post(f"{API}/v1/agents/register", json=body, timeout=30)
    if r.status_code == 201:
        agent = r.json()
        # Patch the payout_wallet so the agent's listings will payout to its own wallet
        # (we'll set this via direct SQL on the server if needed — for now, the
        # listing carries payout_wallet directly).
        print(f"  ✓ {slug:25s} did={agent.get('did', did)}")
        return agent.get("did", did)
    elif r.status_code in (400, 409):
        # Likely already registered (duplicate DID). Fetch current.
        print(f"  • {slug:25s} already registered or rejected: {r.text[:120]}")
        return did
    else:
        print(f"  ✗ {slug:25s} FAILED {r.status_code}: {r.text[:120]}")
        return None


def create_provider_listing(slug: str, addr: str, did: str) -> None:
    """Each provider publishes a service listing with their capability + price."""
    spec = next(p for p in PROVIDERS if p.slug == slug)
    body = {
        "seller_kind": "agent",
        "seller_did": did,
        "payout_wallet": addr,
        "listing_type": "service",
        "title": f"{spec.name} — {spec.capability}",
        "description": spec.description,
        "category": spec.capability.lower(),
        "tags": [spec.capability.lower(), "swarm"],
        "price_amount": str(spec.base_price_usdc),
        "price_currency": "USDC",
        "service_capability": spec.capability,
        "service_input_schema": {"schema_hint": spec.input_schema_hint},
    }
    r = httpx.post(f"{API}/v1/listings", json=body, timeout=20)
    if r.status_code == 201:
        listing = r.json()
        print(f"    listing: {listing['id']} @ {listing['price_amount']} USDC")
    else:
        print(f"    listing FAILED {r.status_code}: {r.text[:150]}")


def main() -> None:
    if not WALLETS_FILE.exists():
        sys.exit("wallets.json missing — run wallet_setup.py --gen first")
    wallets = json.loads(WALLETS_FILE.read_text())
    if not wallets:
        sys.exit("wallets.json is empty — run wallet_setup.py --gen first")

    dids: dict[str, str] = {}
    print("=== Registering 20 agents ===")
    for slug, w in wallets.items():
        d = register_agent(slug, w["role"], w["address"], w["private_key"])
        if d:
            dids[slug] = d

    print("\n=== Publishing provider listings ===")
    for slug, w in wallets.items():
        if w["role"] == "provider" and slug in dids:
            create_provider_listing(slug, w["address"], dids[slug])

    # Persist did-mapping for the runtime loops
    out = Path(__file__).parent / "data" / "dids.json"
    out.write_text(json.dumps(dids, indent=2))
    print(f"\nWrote DID map → {out}")


if __name__ == "__main__":
    main()
