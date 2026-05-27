"""Sprint 20 — End-to-End-Test for the Audit Document Gap Checker.

Drives the full x402 lifecycle from the buyer side:

  1. hire_with_x402: POST /v1/x402/jobs → 402 → on-chain approve + createJob → retry
  2. Poll /v1/jobs/{id} until status='submitted' (Audit-Agent runs Haiku, submits result on-chain)
  3. approve_with_x402: POST /v1/x402/jobs/{id}/approve → 402 → on-chain approveAndPay → retry
  4. GET /v1/jobs/{id} → display the result envelope

Uses one of the existing swarm-buyer wallets as the requester so we
don't need a separate funded wallet. Run on the server:

  /opt/agora/apps/backend/.venv/bin/python3 test_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

API = "https://api.agoraproto.org"
RPC = "https://sepolia.base.org"
AUDIT_LISTING_ID = "53427bdc-b5dd-4873-b543-9532213328cb"
AUDIT_AGENT_DID = "did:agora:bootstrap-0HvnYywMRQvo9-B8SfjWIg"
BUDGET_USDC = "0.01"
BUYER_SLUG = "marketing-alice"  # any swarm buyer works
POLL_TIMEOUT_SECONDS = 180
POLL_INTERVAL = 5

# Test scenario — intentionally weak ISO 9001 process description so we
# get a meaningful gap report.
TASK_SPEC = {
    "standard": "iso9001",
    "document": (
        "Unsere Firma ist ein Zulieferer für Automobilteile. Wir haben einen "
        "Geschäftsführer, der gleichzeitig Qualitätsbeauftragter ist. Es gibt "
        "keine schriftliche Qualitätspolitik, aber alle Mitarbeiter wissen, "
        "dass Qualität wichtig ist. Reklamationen werden in einer Excel-"
        "Tabelle erfasst. Audits machen wir, wenn der Kunde kommt — etwa "
        "einmal im Jahr. Lieferantenauswahl: günstigstes Angebot. Schulungen "
        "finden statt, wenn ein Mitarbeiter darum bittet."
    ),
}


# ─── Helpers ─────────────────────────────────────────────────────────


def load_buyer() -> tuple[str, str, str]:
    """Return (slug, did, private_key) for the test-buyer.

    Sprint 30 fix: Stopped using marketing-alice (a swarm buyer whose
    own buyer-loop kept racing our test-script and draining her USDC).
    Now uses a dedicated test-buyer bootstrapped via /v1/agents/bootstrap
    that has no other process touching her wallet.
    """
    test_buyer_file = Path("/opt/agora/experiments/audit_agent/data/test_buyer.json")
    if test_buyer_file.is_file():
        creds = json.loads(test_buyer_file.read_text())
        return "test-buyer", creds["did"], creds["evm_private_key_hex"]
    # Fallback to swarm buyer if test_buyer.json missing
    swarm = Path("/opt/agora/experiments/swarm/data")
    if not (swarm / "wallets.json").is_file():
        sys.exit("test_buyer.json missing and no swarm wallets available")
    wallets = json.loads((swarm / "wallets.json").read_text())
    dids = json.loads((swarm / "dids.json").read_text())
    if BUYER_SLUG not in wallets:
        sys.exit(f"buyer {BUYER_SLUG!r} not in wallets.json")
    w = wallets[BUYER_SLUG]
    did = dids.get(BUYER_SLUG)
    if not did:
        sys.exit(f"buyer {BUYER_SLUG!r} has no DID")
    return BUYER_SLUG, did, w["private_key"]


async def poll_job(jid: str, target_status: str) -> dict:
    """Poll /v1/jobs/{jid} until status==target_status. Returns the job dict."""
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    last_status = None
    async with httpx.AsyncClient(timeout=15) as http:
        while time.time() < deadline:
            r = await http.get(f"{API}/v1/jobs/{jid}")
            if r.status_code == 200:
                job = r.json()
                s = job.get("status")
                if s != last_status:
                    print(f"  · job status: {s}")
                    last_status = s
                if s == target_status:
                    return job
                if s in ("expired", "refunded"):
                    sys.exit(f"job ended with status={s} (wanted {target_status})")
            await asyncio.sleep(POLL_INTERVAL)
    sys.exit(f"timeout: job {jid} never reached status={target_status}")


# ─── Main ────────────────────────────────────────────────────────────


async def main() -> None:
    slug, buyer_did, buyer_key = load_buyer()
    print(f"=== Test buyer: {slug} ({buyer_did}) ===")
    print(f"=== Provider:   Audit Document Gap Checker ({AUDIT_AGENT_DID}) ===")
    print(f"=== Listing:    {AUDIT_LISTING_ID} @ {BUDGET_USDC} USDC ===\n")

    try:
        from agora_sdk.x402 import approve_with_x402, hire_with_x402
    except ImportError:
        sys.exit("agora_sdk not installed; pip install -e /opt/agora/packages/sdk-python")

    # ── 1. Hire ───────────────────────────────────────────────────
    print("[1/4] Hiring the audit agent (x402: approve + createJob on-chain)")
    t0 = time.time()
    hire_res = await hire_with_x402(
        API,
        requester_did=buyer_did,
        provider_did=AUDIT_AGENT_DID,
        task=TASK_SPEC,
        budget_usdc=BUDGET_USDC,
        rpc_url=RPC,
        private_key=buyer_key,
        deadline_seconds=10 * 60,
    )
    job_id = hire_res.get("id") or hire_res.get("job_id")
    if not job_id:
        sys.exit(f"hire returned no id: {hire_res}")
    print(f"  ✓ job_id = {job_id}  (took {time.time()-t0:.1f}s)")

    # ── 2. Wait for submission ────────────────────────────────────
    print(f"\n[2/4] Waiting for Audit Agent to submit a result (timeout {POLL_TIMEOUT_SECONDS}s)")
    job = await poll_job(job_id, "submitted")
    print(f"  ✓ result_hash on-chain: {job.get('result_hash', '?')[:18]}…")

    # ── 3. Approve & pay ─────────────────────────────────────────
    print("\n[3/4] approveAndPay — releasing escrow to the provider")
    # Race condition: if the buyer DID belongs to a swarm Buyer, its
    # systemd loop may already have approved this job on its own poll
    # cycle, leaving the on-chain status = Approved. Our own approve
    # would then revert with InvalidStatus(0xf525e320). Treat that as
    # "already approved by the other agent" — the job is paid either way.
    try:
        await approve_with_x402(
            API,
            job_id=job_id,
            rpc_url=RPC,
            private_key=buyer_key,
        )
        print(f"  ✓ escrow released")
    except Exception as e:
        msg = str(e)
        is_invalid_status = "0xf525e320" in msg or "InvalidStatus" in msg
        if not is_invalid_status:
            raise
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.get(f"{API}/v1/jobs/{job_id}")
        full = r.json() if r.status_code == 200 else {}
        if full.get("status") == "completed":
            print(f"  ✓ already approved by another agent "
                  f"(swarm buyer loop won the race) — job is paid")
        else:
            print(f"  ✗ InvalidStatus but DB status is {full.get('status')!r}")
            raise

    # ── 4. Fetch the actual result envelope ──────────────────────
    print("\n[4/4] Fetching the result envelope")
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(f"{API}/v1/jobs/{job_id}")
    r.raise_for_status()
    job = r.json()
    result = job.get("result") or {}
    summary = result.get("summary", {})
    report = result.get("markdown_report", "")

    print(f"\n────────── Summary ──────────")
    print(f"  overall_score_pct:    {summary.get('overall_score_pct')}")
    print(f"  critical_gaps_count:  {summary.get('critical_gaps_count')}")
    print(f"  satisfied_clauses:    {len(summary.get('satisfied_clauses', []))}")
    print(f"  gap_clauses:          {len(summary.get('gap_clauses', []))}")
    print(f"  unclear_clauses:      {len(summary.get('unclear_clauses', []))}")
    print(f"  top_recommendations:  {len(summary.get('top_recommendations', []))}")
    if summary.get("top_recommendations"):
        print(f"\n  Top recommendations:")
        for i, rec in enumerate(summary["top_recommendations"][:5], 1):
            print(f"    {i}. {rec}")

    print(f"\n────────── Markdown report (first 2 000 chars) ──────────")
    print(report[:2000])
    if len(report) > 2000:
        print(f"\n… (truncated; full report is {len(report)} chars, full job at {API}/v1/jobs/{job_id})")

    print(f"\n✅ End-to-End successful — full job: {API}/v1/jobs/{job_id}")


if __name__ == "__main__":
    asyncio.run(main())
