# Sprint 9f — Full x402 lifecycle through the API

**Date:** 2026-05-20 (continuation of Sprint 9e)
**Goal:** make a complete agent-to-agent trade run end-to-end through
the live API, with no manual `cast` invocations on either side.

## What was missing before this sprint

Sprint 9b shipped the `hire` half of the lifecycle:

```
POST /v1/x402/jobs → 402 + X-Payment-Required (createJob args)
on-chain pay
POST /v1/x402/jobs + X-Payment-Tx → 201
```

But once a job was created, the *only* way to drive it to completion
was raw `cast` calls against `AgoraEscrow.submitResult` /
`approveAndPay` / `refund`. The API didn't speak the other three sides
of the contract's state machine.

So Job #3 (the first HTTP x402 trade, on the morning of 2026-05-20) sat
indefinitely in `status="offered"` with 1 USDC locked in escrow. The
protocol worked, but a real-world deployment would need provider and
requester to do half their work via raw chain calls.

## What this sprint added

Three new endpoints, mirroring the existing hire pattern:

| Endpoint | Role | Contract call |
|---|---|---|
| `POST /v1/x402/jobs/{job_id}/result` | provider | `AgoraEscrow.submitResult(jobId, resultHash)` |
| `POST /v1/x402/jobs/{job_id}/approve` | requester | `AgoraEscrow.approveAndPay(jobId)` |
| `POST /v1/x402/jobs/{job_id}/refund` | requester | `AgoraEscrow.refund(jobId)` |

Each follows the same x402 pattern as the existing hire flow:

1. **First POST** — no `X-Payment-Tx`. Server returns `402 Payment
   Required` with `X-Payment-Required` describing the exact contract
   call to make (function name, args, deadline).
2. **Agent signs and broadcasts** the on-chain transaction. The
   contract's per-role guards (`NotPayee`, `NotPayer`) ensure only the
   right party can execute each step — the API never needs to
   authenticate the caller because the chain already does.
3. **Retry POST** with `X-Payment-Tx: 0x...`. The server fetches the
   receipt, parses the matching event (`ResultSubmitted`, `JobApproved`,
   or `JobRefunded`), re-verifies the event's args match the request,
   and mirrors the state change in Postgres.

## What also changed

- **`AgoraEscrowClient` ABI** got the three missing events:
  `ResultSubmitted`, `JobDisputed`, `JobRefunded`. Without these, the
  server couldn't `process_log` the on-chain side effects of the new
  endpoints.

- **Python SDK** (`packages/sdk-python/src/agora_sdk/x402.py`):
  three new helpers — `submit_result_with_x402`, `approve_with_x402`,
  `refund_with_x402` — that wrap the 402-then-on-chain-then-retry dance.
  Each takes only the SDK base URL, the job ID, an RPC URL, and the
  caller's Ethereum private key. Version bump 0.4.0 → 0.5.0.

- **TypeScript SDK** (`packages/sdk-typescript/src/x402.ts`): same
  three helpers — `submitResultWithX402`, `approveWithX402`,
  `refundWithX402` — built on a shared `lifecycleCall` driver that
  uses `viem`. Version bump 0.4.0 → 0.5.0.

- **`docs/x402.md`**: rewrote the TL;DR and added endpoint sections for
  the new three. Updated SDK examples to show the full lifecycle.

- **Test coverage**: 12 new pytest cases in `test_x402_endpoint.py`
  exercising the new endpoints — the 402-first-call path, the
  retry-with-tx happy path, the wrong-status / wrong-hash / offchain
  guards, and idempotency for already-completed jobs. Sprint 9b's
  enqueue_for_agent bug would have been caught if these existed.

- **`agents_repo.get_by_id`** added (lookup by PK rather than DID). The
  new endpoints need full Agent objects to drive `enqueue_for_agent`,
  and the foreign keys on `jobs` are by `agents.id`.

## What this unlocks

With the full lifecycle in the API, an agent (or an SDK using the
helpers) can now drive a complete trade with **four HTTP calls and four
on-chain transactions**, no raw `cast` invocations required:

```
[REQUESTER]  POST /v1/x402/jobs              → 402 → createJob() → POST retry  → status="offered"
[PROVIDER]   POST /v1/x402/jobs/{id}/result  → 402 → submitResult() → POST retry → status="submitted"
[REQUESTER]  POST /v1/x402/jobs/{id}/approve → 402 → approveAndPay() → POST retry → status="completed"
```

The settlement-mode split is now clean:
- Off-chain ledger flow lives at `/v1/jobs/...` (unchanged).
- On-chain x402 flow lives at `/v1/x402/jobs/...` (now complete).

## What this does NOT yet do

- **Off-chain endpoints don't guard against on-chain jobs.** If
  somebody POSTs to `/v1/jobs/{onchain_job_id}/approve`, the existing
  off-chain handler will try `ledger_repo.release_escrow` and fail with
  an opaque error. Should add a 409 with "use /v1/x402/... instead".
  Minor cleanup.
- **Chain watcher background task.** If a party calls the contract
  directly (bypassing the API), the DB stays stale. Sprint 9g should
  add a periodic poll that reconciles on-chain `jobs(jobId).status`
  with our DB.
- **Dispute on-chain.** The contract has `dispute(jobId, reason)` and
  emits `JobDisputed`; the API doesn't expose it yet. The off-chain
  dispute Stage-1 code-as-judge still runs through `/v1/jobs/{id}/dispute`.
- **No formal audit yet.** Mainnet remains gated on third-party audit
  per ADR 009.

## Status table after this sprint

```
hire     ✅ live, tested live (Jobs #2 + #3)
result   ✅ live in code & tests, not yet exercised live
approve  ✅ live in code & tests, not yet exercised live
refund   ✅ live in code & tests, not yet exercised live
```

The next pending milestone is to drive Job #3 (the existing on-chain
job from Sprint 9e) to completion via the new `result` + `approve`
endpoints, end-to-end through the live API. That closes the loop and
unblocks the public announcement (Sprint 9e/task #85).
