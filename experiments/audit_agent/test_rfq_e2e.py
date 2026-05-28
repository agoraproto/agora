"""Sprint 31b — End-to-End demo of the demand-side marketplace.

Buyer flow:
  1. POST /v1/requests          — buyer posts an RFQ for AuditDocumentGapCheck
  2. Wait for Audit-Agent to     — RfqListener polls every 15 s, signs + posts
     submit a signed bid           a bid via POST /v1/requests/{id}/bids
  3. POST .../bids/{bid_id}/    — buyer accepts the bid
     accept
  4. hire_with_x402 →            — standard x402 hire on the bid's provider_did
     submit_result_with_x402 →     (same as test_e2e.py, but with the task spec
     approve_with_x402            agreed in the RFQ)
  5. Fetch result envelope       — verify the compliance gap report

Run on the server:
  /opt/agora/apps/backend/.venv/bin/python3 \\
    /opt/agora/experiments/audit_agent/test_rfq_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

API = "https://api.agoraproto.org"
RPC = "https://sepolia.base.org"
BUDGET_USDC = "0.01"
BID_WAIT_TIMEOUT_S = 90      # how long to wait for the Audit-Agent to bid
JOB_WAIT_TIMEOUT_S = 180     # how long for the provider to submitResult

TEST_BUYER_FILE = Path("/opt/agora/experiments/audit_agent/data/test_buyer.json")
TASK_SPEC = {
    "standard": "iso9001",
    "document": (
        "Wir produzieren CNC-gefräste Aluminiumteile für die Luftfahrt. "
        "Qualitätssicherung läuft über zwei Wege: jeder Maschinenbediener "
        "macht eine Sichtprüfung am Ende seiner Schicht; und einmal die "
        "Woche misst ein erfahrener Kollege Stichproben mit dem Bügelmessschrauber "
        "nach. Reklamationen kommen ein paar Mal im Jahr — der Geschäftsführer "
        "ruft den Kunden an und klärt persönlich. Wir haben keine schriftlichen "
        "Verfahren, weil alle wissen wie es läuft. Lieferantenwahl trifft "
        "der Einkauf nach Bauchgefühl."
    ),
}


def load_test_buyer() -> dict:
    if not TEST_BUYER_FILE.is_file():
        sys.exit(f"missing {TEST_BUYER_FILE} — bootstrap a test-buyer first")
    return json.loads(TEST_BUYER_FILE.read_text())


async def post_rfq(http: httpx.AsyncClient, buyer_did: str) -> str:
    body = {
        "buyer_did": buyer_did,
        "title": "ISO 9001 compliance gap — aerospace CNC supplier",
        "description": "Need a structured gap report for our QMS scenario.",
        "capability": "AuditDocumentGapCheck",
        "constraints": {"task_spec": TASK_SPEC},
        "max_price_micro_usdc": 10_000,
        "currency": "USDC",
        "deadline": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    r = await http.post(f"{API}/v1/requests", json=body)
    if r.status_code != 201:
        sys.exit(f"POST /v1/requests failed: {r.status_code} {r.text[:400]}")
    req = r.json()
    print(f"  ✓ rfq_id = {req['id']}")
    print(f"  ✓ status = {req['status']}")
    print(f"  ✓ max_price = {req['max_price_micro_usdc']} micro-USDC")
    return req["id"]


async def wait_for_bid(http: httpx.AsyncClient, rfq_id: str, capability_provider_hint: str | None = None) -> dict:
    """Poll the RFQ until at least one bid lands. Returns the chosen bid dict."""
    deadline = time.time() + BID_WAIT_TIMEOUT_S
    last_count = -1
    while time.time() < deadline:
        r = await http.get(f"{API}/v1/requests/{rfq_id}")
        if r.status_code == 200:
            req = r.json()
            bids = req.get("bids", []) or []
            if len(bids) != last_count:
                print(f"  · bids so far: {len(bids)}")
                last_count = len(bids)
            if bids:
                # If a specific provider DID is preferred, pick that one;
                # otherwise pick the lowest price bid.
                if capability_provider_hint:
                    matching = [b for b in bids if b.get("provider_did") == capability_provider_hint]
                    if matching:
                        return matching[0]
                bids_sorted = sorted(bids, key=lambda b: int(b.get("price_micro_usdc", 1 << 31)))
                return bids_sorted[0]
        await asyncio.sleep(5)
    sys.exit(f"no bid received within {BID_WAIT_TIMEOUT_S}s")


async def accept_bid(http: httpx.AsyncClient, rfq_id: str, bid: dict, buyer_did: str) -> None:
    body = {"buyer_did": buyer_did, "bid_hash": bid["bid_hash"]}
    r = await http.post(f"{API}/v1/requests/{rfq_id}/bids/{bid['id']}/accept", json=body)
    if r.status_code not in (200, 201):
        sys.exit(f"accept failed: {r.status_code} {r.text[:400]}")
    print(f"  ✓ accepted bid {bid['id'][:8]} from {bid['provider_did'][:30]}…")
    print(f"  ✓ price        = {bid['price_micro_usdc']} micro-USDC")


async def hire_provider(creds: dict, provider_did: str, task: dict) -> str:
    """Standard x402 hire on the winning provider. Returns job_id."""
    from agora_sdk.x402 import hire_with_x402
    hire_res = await hire_with_x402(
        API,
        requester_did=creds["did"],
        provider_did=provider_did,
        task=task,
        budget_usdc=BUDGET_USDC,
        rpc_url=RPC,
        private_key=creds["evm_private_key_hex"],
        deadline_seconds=10 * 60,
    )
    job_id = hire_res.get("id") or hire_res.get("job_id")
    if not job_id:
        sys.exit(f"hire returned no id: {hire_res}")
    print(f"  ✓ job_id = {job_id}")
    return job_id


async def poll_job(http: httpx.AsyncClient, job_id: str, target_status: str) -> dict:
    deadline = time.time() + JOB_WAIT_TIMEOUT_S
    last_status = None
    while time.time() < deadline:
        r = await http.get(f"{API}/v1/jobs/{job_id}")
        if r.status_code == 200:
            j = r.json()
            s = j.get("status")
            if s != last_status:
                print(f"  · job status: {s}")
                last_status = s
            if s == target_status:
                return j
            if s in ("expired", "refunded"):
                sys.exit(f"job ended in {s} (wanted {target_status})")
        await asyncio.sleep(5)
    sys.exit(f"timeout waiting for {target_status}")


async def main() -> None:
    creds = load_test_buyer()
    buyer_did = creds["did"]
    print(f"=== Test-Buyer: {buyer_did} ===")
    print(f"=== Capability requested: AuditDocumentGapCheck ===\n")

    async with httpx.AsyncClient(timeout=30) as http:
        # 1) Post RFQ
        print("[1/6] Posting RFQ on /v1/requests")
        rfq_id = await post_rfq(http, buyer_did)

        # 2) Wait for Audit-Agent's bid (rfq_listener polls every 15s)
        print(f"\n[2/6] Waiting for a bid (timeout {BID_WAIT_TIMEOUT_S}s)")
        bid = await wait_for_bid(http, rfq_id)

        # 3) Accept the bid
        print("\n[3/6] Accepting the bid")
        await accept_bid(http, rfq_id, bid, buyer_did)

    # 4) Standard x402 hire on the winning provider
    print("\n[4/6] x402 hire on the winning provider")
    job_id = await hire_provider(creds, bid["provider_did"], TASK_SPEC)

    # 5) Wait for submitted
    print(f"\n[5/6] Waiting for provider to submit result (timeout {JOB_WAIT_TIMEOUT_S}s)")
    async with httpx.AsyncClient(timeout=30) as http:
        job = await poll_job(http, job_id, "submitted")

        # 6) approveAndPay (may race with the provider's own approve; tolerate)
        print("\n[6/6] approveAndPay")
        from agora_sdk.x402 import approve_with_x402
        try:
            await approve_with_x402(API, job_id=job_id, rpc_url=RPC, private_key=creds["evm_private_key_hex"])
            print("  ✓ escrow released")
        except Exception as e:
            if "0xf525e320" in str(e) or "InvalidStatus" in str(e):
                print("  ✓ already approved (raced with provider) — fine")
            else:
                raise

        # Fetch result envelope
        r = await http.get(f"{API}/v1/jobs/{job_id}")
        result = r.json().get("result") or {}
        summary = result.get("summary", {})
        print(f"\n────────── RFQ-Audit envelope ──────────")
        print(f"  overall_score_pct:   {summary.get('overall_score_pct')}")
        print(f"  critical_gaps:        {summary.get('critical_gaps_count')}")
        print(f"  gap_clauses:          {len(summary.get('gap_clauses', []) or [])}")
        print(f"  top_recommendations:  {len(summary.get('top_recommendations', []) or [])}")
        for i, rec in enumerate((summary.get("top_recommendations") or [])[:5], 1):
            print(f"    {i}. {rec}")

    print(f"\n✅ RFQ E2E successful — RFQ {rfq_id} → bid → x402 hire → result → settled")
    print(f"   Full job: {API}/v1/jobs/{job_id}")


if __name__ == "__main__":
    asyncio.run(main())
