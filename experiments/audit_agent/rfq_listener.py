"""Sprint 31b — Provider-side RFQ listener for the Audit Document Gap Checker.

Polls /v1/requests for open RFQs matching this agent's capability, signs a
bid, and submits it via POST /v1/requests/{id}/bids. The agent only listens
— actual job execution stays in agent.py's main poll-loop and triggers when
a buyer accepts a bid and issues a regular x402 hire.

Why polling instead of webhook?
The current rfq.py emits webhook events only on bid.created (to the buyer)
and bid.accepted (to the provider). There is no request.created broadcast,
so providers have to discover new RFQs on their own. Polling every 15s is
cheap and gives the swarm a fair shot at every request.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from nacl.signing import SigningKey

API = os.environ.get("AGORA_API", "https://api.agoraproto.org")
POLL_INTERVAL_RFQ = int(os.environ.get("AUDIT_RFQ_POLL_INTERVAL", "15"))
CAPABILITY = "AuditDocumentGapCheck"
# Bid slightly below the house-rule ceiling so we win when multiple
# Audit-Agents end up competing. With one live agent today it's just
# a sensible default below max_price_micro_usdc=10000 (0.01 USDC).
DEFAULT_BID_PRICE_MICRO_USDC = 8_000  # 0.008 USDC
BID_VALIDITY_MINUTES = 5

HERE = Path(__file__).parent
CREDS_FILE = HERE / "data" / "credentials.json"

log = logging.getLogger("audit_agent.rfq")


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class RfqListener:
    def __init__(self, did: str, ed25519_private_key_hex: str) -> None:
        self.did = did
        self.signing_key = SigningKey(bytes.fromhex(ed25519_private_key_hex))
        self.already_bid_on: set[str] = set()  # request_id strings

    async def run(self) -> None:
        log.info(
            "rfq listener online (did=%s, capability=%s, poll=%ds)",
            self.did, CAPABILITY, POLL_INTERVAL_RFQ,
        )
        while True:
            try:
                await self._tick()
            except Exception as e:
                log.exception("rfq tick failed: %s", e)
            await asyncio.sleep(POLL_INTERVAL_RFQ)

    async def _tick(self) -> None:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.get(
                f"{API}/v1/requests",
                params={"status_filter": "open", "capability": CAPABILITY, "limit": 50},
            )
        if r.status_code != 200:
            return
        data = r.json()
        requests = data.get("requests", [])
        if not requests:
            return
        log.debug("rfq: %d open requests for capability=%s", len(requests), CAPABILITY)
        async with httpx.AsyncClient(timeout=15) as http:
            for req in requests:
                rid = req.get("id")
                if not rid or rid in self.already_bid_on:
                    continue
                # Don't bid on our own requests
                if req.get("buyer_did") == self.did:
                    self.already_bid_on.add(rid)
                    continue
                try:
                    await self._submit_bid(http, req)
                    self.already_bid_on.add(rid)
                except Exception as e:
                    log.warning("bid on %s failed: %s", rid, e)

    async def _submit_bid(self, http: httpx.AsyncClient, req: dict[str, Any]) -> None:
        rid = req["id"]
        max_price = int(req.get("max_price_micro_usdc", 0))
        price = min(DEFAULT_BID_PRICE_MICRO_USDC, max_price)
        if price <= 0:
            log.info("rfq %s has max_price=0, skipping", rid)
            return

        nonce = secrets.token_hex(16)
        expires_at = datetime.now(UTC) + timedelta(minutes=BID_VALIDITY_MINUTES)
        # Canonical signed_payload — must mirror the API's expected schema
        signed_payload = {
            "request_id": rid,
            "provider_did": self.did,
            "price_micro_usdc": price,
            "currency": "USDC",
            "nonce": nonce,
            "expires_at": expires_at.isoformat(),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        # Sign the canonical bytes with our Ed25519 key
        sig_bytes = self.signing_key.sign(_canonical_json(signed_payload)).signature
        signature_b64 = base64.b64encode(sig_bytes).decode("ascii")

        body = {
            "provider_did": self.did,
            "price_micro_usdc": price,
            "currency": "USDC",
            "message": (
                f"Compliance gap check for {req.get('capability', 'AuditDocumentGapCheck')}. "
                "Delivery: structured JSON envelope with markdown_report and summary "
                "(satisfied_clauses, gap_clauses with severity, top_recommendations)."
            ),
            "signed_payload": signed_payload,
            "signature": signature_b64,
            "nonce": nonce,
            "expires_at": expires_at.isoformat(),
        }
        r = await http.post(f"{API}/v1/requests/{rid}/bids", json=body)
        if r.status_code == 201:
            bid = r.json()
            log.info(
                "rfq: bid %s on request %s @ %d micro-USDC",
                bid.get("id", "?")[:8], rid[:8], price,
            )
        else:
            log.warning("rfq: bid on %s rejected: %s %s",
                        rid[:8], r.status_code, r.text[:200])


# Standalone entry point if you want to run the listener alone
async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [audit-rfq] %(message)s",
        datefmt="%H:%M:%S",
    )
    if not CREDS_FILE.is_file():
        raise SystemExit(f"missing {CREDS_FILE} — run register.py first")
    creds = json.loads(CREDS_FILE.read_text())
    listener = RfqListener(
        did=creds["did"],
        ed25519_private_key_hex=creds["ed25519_private_key_hex"],
    )
    await listener.run()


if __name__ == "__main__":
    asyncio.run(main())
