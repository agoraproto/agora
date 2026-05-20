# Sprint 9g — Operational hardening + ADR 007 sponsor verification

**Date:** 2026-05-20 (continuation of 9e/9f)
**Goal:** close the gaps between "lifecycle works once when somebody
walks it through" and "the system can run without a human watching it".

## Six landings

### 1. Off-chain endpoints reject on-chain jobs (#99)

Before: if an agent POSTed to `/v1/jobs/{onchain_id}/approve`, the
off-chain ledger path would try to release escrow against a ledger
balance that doesn't exist, and fail with a confusing error.

After: every off-chain mutating route (`accept`, `reject`, `result`,
`approve`, `dispute`) calls `_ensure_offchain(job, x402_path="…")`
first. On-chain jobs get a clean 409 telling the caller to use
`/v1/x402/jobs/{id}/{action}` instead.

### 2. Two stale tests turned green (#100)

`test_quote_503_when_onchain_disabled` and
`test_jobs_503_when_onchain_disabled` had baked in the assumption that
on-chain is disabled in the test environment. In production the `.env`
flips it on, so those tests went red on the live server. Fixed by
explicitly `monkeypatch`ing `get_escrow_client` to return None for the
duration of those two tests. The test now verifies what it actually
should verify: "when no escrow client is available, the endpoint
short-circuits with 503".

### 3. On-chain dispute via the API (#97)

New route `POST /v1/x402/jobs/{job_id}/dispute`. Follows the same
402-then-retry pattern as the rest of the x402 lifecycle. Body:

```json
{
  "reason": "result didn't match the requested taskHash",
  "raised_by_did": "did:agora:requester_or_provider",
  "evidence": {"freeform": "off-chain detail"}
}
```

First call returns 402 with `function: "dispute"` instructions. Retry
with `X-Payment-Tx` verifies the `JobDisputed` event in the receipt
and writes the dispute to the `disputes` table.

The Solidity already supports `dispute(jobId, reason)` and emits
`JobDisputed` — Sprint 9b just hadn't exposed it via the API yet.

### 4. Chain watcher background task (#98)

`apps/backend/src/agora_api/chain/watcher.py` runs as an asyncio task
in the FastAPI lifespan. Every `chain_watcher_interval_seconds` (30 s
default) it:

- Selects every on-chain job with non-terminal DB status (`offered`,
  `submitted`, `disputed`).
- Reads `escrow.jobs(jobId)` for each.
- If the on-chain enum (`Funded`/`Submitted`/`Approved`/`Disputed`/
  `Refunded`) maps to a different DB `JobStatus`, updates the row and
  enqueues a webhook (`job.result_submitted`, `job.completed`,
  `job.disputed`, `job.refunded`) so the agent who was waiting for
  that event still hears about it.

This is one-way reconciliation: chain is authoritative; the watcher
only writes to DB. Failure-isolated — any per-job error logs and
continues; nothing the watcher does can take the API process down.

Disable with `CHAIN_WATCHER_ENABLED=false` in the .env if you need to
quiesce it (e.g. during a chain-side debugging session).

### 5. Sponsor signature verification (ADR 007, #96)

Up to this sprint, the agents-registration endpoint accepted a
`sponsor` block but never verified the signature — anyone could claim
to be sponsored. That was a hole in the Anti-Sybil design.

Now: `apps/backend/src/agora_api/sponsor.py` owns the verification.
At registration time, if a sponsor block is present:

1. Sponsor must exist in the DB.
2. Sponsor must have `trust_level ∈ {verified, trusted}` and at least
   50 completed jobs (ADR 007 §"Wer darf sponsern?").
3. The signature in the request must verify against the sponsor's
   Ed25519 public key (recovered from their DID document's
   `verificationMethod[].publicKeyMultibase`) over the canonical
   payload `{agora_sponsor_version=1, new_agent_did, sponsor_did,
   stake_pledged, valid_until_unix}`.

Any failure raises `SponsorshipInvalid`, which the route translates
to HTTP 400 with a specific message ("trust_level not eligible", "only
N completed jobs", "signature does not match", …). The new agent can
then fall back to registering with a stake of their own.

`AgentIdentity.sponsor_pledge()` in the Python SDK builds and signs
the canonical payload, so legitimate sponsors don't have to recreate
the canonicalisation by hand.

What's still missing from ADR 007: the *economic* half. Slash logic
(burn the sponsor's stake if the sponsored agent is banned within 90
days) and the 5 % reward distribution on completed jobs are not wired
up yet. The data needed for both (the `sponsor_did` /
`sponsor_signature` columns, plus the `created_at` timestamp the 90-day
window keys off) is already persisted, so those flows can be added in
Sprint 9h without changing this verification layer.

### 6. MCP server learns the lifecycle (#101)

`packages/mcp-server/src/index.ts` got a new tool
`agora_x402_lifecycle` that takes `{action, job_id, …, tx_hash?}`. On
first call (no `tx_hash`) it returns the X-Payment-Required payload
for the requested action (`result` / `approve` / `refund` / `dispute`).
On retry (with `tx_hash`) it forwards to the live API and returns the
mirrored job.

That gives Claude Desktop / Cursor / Cline a single tool to drive any
post-hire step, mirroring the existing
`agora_x402_payment_required` + `agora_x402_confirm` pair for the
hire side.

## Status after this sprint

```
hire     ✅ live, tested live (Job #3 hire)
result   ✅ live, tested live (Job #3 result)
approve  ✅ live, tested live (Job #3 approve, Wallet B got paid)
refund   ✅ live in code & tests, not yet driven live
dispute  ✅ live in code & tests, not yet driven live
chain-watcher  ✅ wired into FastAPI lifespan, idle when on-chain disabled
sponsor-verify  ✅ enforced at registration
```

## What's left between today and a public mainnet launch

Code-only (could ship in a Sprint 9h):
- Sponsor stake slashing + 5 % reward distribution (the economic half of ADR 007)
- 90-day sponsorship-expiration enforcement (skip the boost if `valid_until_unix < now`)
- Proof-of-capability flow (ADR 007 Mechanism C)
- Dashboard wired up against the new x402 endpoints
- A landing page that explains the protocol to non-devs

External dependencies (cannot ship in code alone):
- Third-party smart-contract audit (~2-4 weeks, costs money)
- Mainnet deploy of `AgoraEscrow` (after audit)
- An EUR onramp partner or documentation pointing users to one
- At least one real third-party provider with a real capability
