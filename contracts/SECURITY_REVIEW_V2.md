# AgoraEscrowV2 — Internal Self-Audit

**Target:** `contracts/src/AgoraEscrowV2.sol` (Solidity 0.8.26, ~361 lines)
**Tests:** `contracts/test/AgoraEscrowV2.t.sol` (20 forge tests, all green)
**Deployed (testnet):** [`0x0e8E6A760c76cA92c5C5dA06d293E33f1B5fbAEc`](https://sepolia.basescan.org/address/0x0e8E6A760c76cA92c5C5dA06d293E33f1B5fbAEc#code) on Base Sepolia
**Owner:** 2-of-2 Gnosis Safe [`0x8Ec63Fe30DAb84308B5009b8D91d9E4dEB5a61FC`](https://sepolia.basescan.org/address/0x8Ec63Fe30DAb84308B5009b8D91d9E4dEB5a61FC) (Sprint 37)
**Reviewer:** internal builder self-audit, Sprint 39 (2026-06-01)
**Status:** **NOT a substitute for external audit.** Findings here are surfaced as a transparency exercise to make external reviewer time more productive.

---

## 1. Executive Summary

V2 was designed to close the 14 findings against V1 (see [`SECURITY_REVIEW.md`](SECURITY_REVIEW.md) for the V1 review). All 14 are addressed at the protocol-design level — the V2 NatSpec at the top of the file lists them inline. The Foundry test suite (20 tests) exercises the happy paths and the key invariants.

This self-audit re-reads V2 with a fresh adversarial mindset and finds **2 MEDIUM**, **2 LOW**, and **5 INFORMATIONAL** issues that V2 did not address — most of them shaped by the "late approval grace" design decision that V2 deliberately took. Plus **1 HIGH backend / ops finding** in the Privy auth bypass path.

**Would I ship this to mainnet today?** No, but for different reasons than V1. The contract itself is much closer to mainnet-ready; the gaps are now mostly economic / dispute-flow design rather than fund-safety bugs. The single biggest open issue is **M-V2-01** — that the owner is on the critical path for any payer who is even slightly slow to approve, which is incompatible with a planned 24h timelock (Sprint 38c) unless we also add a payee-side force-resolution path.

**Two things must be addressed before Mainnet** in my opinion:

1. **M-V2-01 or M-V2-02 fixed** so the owner is an exception path, not a default path for dispute resolution.
2. **B-V2-01 fixed** so a deployment misconfiguration cannot accidentally open the auth bypass.

Everything else in this document is either trivially fixable (L-V2-01, I-V2-01, I-V2-04 — these are fixed in the same sprint as this document) or accepted-design-with-documentation-needed.

---

## 2. Status of V1 Findings in V2

Each of the 14 findings from V1 has a corresponding fix in V2. The reviewer should verify each fix is present.

| ID | V1 Severity | Fix Location in V2 |
|---|---|---|
| C-01 | CRITICAL | `refund()` split into permissionless `refundExpired()` and owner-only `resolveDispute()`. See lines 271-318. |
| H-01 | HIGH | `resolveDispute(jobId, payeeAmount, payerAmount)` added with new `Resolved` terminal state. Lines 275-306. |
| H-02 | HIGH | `dispute()` restricted to `Submitted` state. Line 262. |
| H-03 | HIGH | `submitResult` enforces `block.timestamp <= deadline` (line 222). `approveAndPay` has it commented out as deliberate "late approval grace" (lines 235-238) — see **M-V2-01** below. |
| H-04 | HIGH | `ReentrancyGuard` inherited; `nonReentrant` on every external state-changing fn. |
| H-05 | HIGH | `balanceOf` delta check in `createJob` (lines 190-193). Reverts `AmountMismatch` if fee-on-transfer. |
| H-06 | HIGH | `totalEscrowed` tracked as state variable, line 92, updated in every transfer. |
| M-01 | MEDIUM | `Ownable2Step` inherited, line 41. |
| M-02 | MEDIUM | Zero-address checks in constructor (144-146) and every setter (338, 344). |
| M-03 | MEDIUM | Fee parameters snapshot into Job struct at create-time (lines 204-207). `_computeFeeFor` uses snapshot, line 160. |
| M-04 | MEDIUM | `FeesUpdated`, `FeeRecipientUpdated`, `InsurancePoolUpdated` events emitted on setters. See **I-V2-01** below for asymmetry. |
| M-05 | MEDIUM | `nextJobId = 1` initialized at line 87. |
| L-01 | LOW | `Pausable` inherited; `pause()` / `unpause()` on lines 349-355. |
| L-04 | LOW | `SafeERC20` used for all token transfers. |
| L-05 | LOW | `if (resultHash == bytes32(0)) revert InvalidResultHash();` in `submitResult` line 223. |
| L-06 | LOW | `if (payee == msg.sender) revert SelfJob();` in `createJob` line 184. |

V1 findings: 14 / 14 addressed.

---

## 3. New V2 Findings

Severity scale: same as V1 review (CRITICAL > HIGH > MEDIUM > LOW > INFORMATIONAL).

### MEDIUM

#### M-V2-01 — Stuck-Submitted job forces owner onto critical path of any slow payer

- **Location:** `approveAndPay` lines 231-254, specifically the commented-out deadline check at lines 235-238:
  ```solidity
  // H-03: late approval still allowed (grace) for buyer convenience,
  // but make the semantics explicit. If we ever want strict
  // enforcement, uncomment:
  // if (block.timestamp > j.deadline) revert DeadlineExpired();
  ```

- **Description:** A payee submits a result. Status flips to `Submitted`. From this point onward only the payer can call `approveAndPay` (line 234) or either party can call `dispute` (lines 263). If the payer is unresponsive — bad-faith or simply slow — the job remains in `Submitted` indefinitely. The payee's only on-chain recourse is `dispute()`, which moves the job to `Disputed`, which can only be exited by the owner via `resolveDispute()`.

  This means: **for any payer who doesn't approve within a reasonable window, the owner is the necessary actor**. Combined with the planned 24h timelock ([`TIMELOCK_DESIGN.md`](TIMELOCK_DESIGN.md), Sprint 38c), this also means dispute resolution becomes a minimum-24h+delay flow for benign cases (e.g. payer just got back from vacation, didn't approve in time).

- **Impact:** Centralises a flow that should be exceptional. The protocol's trust-minimisation story gets weaker. With a malicious or compromised owner, the owner can extract value via `resolveDispute(jobId, 0, j.amount)` (refund payer fully) or `resolveDispute(jobId, j.amount, 0)` (full payee payout) on every disputed job.

- **Recommended fix:** add a `payeeForceApprove(jobId)` callable by `j.payee` after `j.deadline + force_approve_grace` (e.g. `deadline + 7 days`), which approves the payment at the payee's risk. Or: allow `dispute` to be raised by payee in `Submitted` state with a separate `payeeUnilateralCancel` path that auto-approves after a longer cool-off (≥7 days from deadline).

  Either way, owner should be a **dispute escalation** path, not the **default path** for "payer was slow."

#### M-V2-02 — refundExpired DoS via late garbage submitResult

- **Location:** `refundExpired` line 311 (`status != Funded` reverts) and `submitResult` lines 214-228 (no caller restriction beyond `payee == msg.sender`).

- **Description:** `refundExpired` only works on `Funded` jobs. A bad-faith payee can wait until immediately before the deadline, submit a garbage `resultHash` (e.g. `keccak256("nope")`), and flip the job to `Submitted`. The payer's clean refund path (which only requires deadline elapsed) is now blocked. Payer must call `dispute()` and depend on the owner's `resolveDispute()`.

- **Impact:** A guaranteed refund flow becomes an owner-dependent flow. Asymmetric: payee unilaterally can take this action; payer cannot pre-emptively prevent it. Owner becomes structurally necessary in another scenario (cf. M-V2-01).

- **Recommended fix:** allow `refundExpired` to work on `Submitted` jobs if and only if `block.timestamp > j.deadline + payer_grace` AND `msg.sender == j.payer`. Pick a grace window (e.g. 3 days post-deadline) where the payer can still demand the refund without involving owner.

### LOW

#### L-V2-01 — Wrong error type for taskHash=0 check

- **Location:** `createJob` line 186:
  ```solidity
  if (taskHash == bytes32(0)) revert InvalidResultHash();
  ```

- **Description:** The error is `InvalidResultHash`, but the check is on `taskHash`. Reads like a copy-paste from the analogous `submitResult` check on `resultHash` (line 223).

- **Impact:** Cosmetic. Integrators decoding the revert reason will look for "result hash issue" when the actual problem is the task commitment.

- **Recommended fix:** add `error InvalidTaskHash();` and use it. **Fixed in this sprint** — see commit attached to this document.

#### L-V2-02 — Precision loss in resolveDispute fee math

- **Location:** `resolveDispute` lines 292-294:
  ```solidity
  uint256 fullFee = _computeFeeFor(j, j.amount);
  fee = (fullFee * payeeAmount) / j.amount;
  if (fee > payeeAmount) fee = payeeAmount;
  ```

- **Description:** Two sequential integer divisions: `(amount * feeBps) / 10_000` inside `_computeFeeFor`, then `(fullFee * payeeAmount) / j.amount` here. For small `payeeAmount` values, the second division can underflow to 0 or be off by ≤2 micro-USDC vs the "obvious" calculation `(payeeAmount * snapshotFeeBps) / 10_000`.

- **Impact:** Negligible at USDC's 6-decimal precision — dust-level. Doesn't break any invariant. But it is a sloppy fee formula that a reviewer will flag.

- **Recommended fix:** compute the proportional fee directly:
  ```solidity
  fee = (payeeAmount * j.snapshotFeeBps) / 10_000;
  if (payeeAmount > 0 && fee < j.snapshotMinFee) fee = j.snapshotMinFee;
  if (fee > j.snapshotMaxFee) fee = j.snapshotMaxFee;
  if (fee > payeeAmount) fee = payeeAmount;
  ```

### INFORMATIONAL

#### I-V2-01 — setFees emits no old values; inconsistent with other setter events

- **Location:** `setFees` line 334 vs `setFeeRecipient` line 339 and `setInsurancePool` line 345.

- **Description:** `FeeRecipientUpdated(oldRecipient, newRecipient)` and `InsurancePoolUpdated(oldPool, newPool)` both emit the old value. `FeesUpdated(feeBps, minFee, maxFee, insuranceShareBps)` emits only the new state. Asymmetric.

- **Recommended fix:** either emit `FeesUpdated(oldFeeBps, oldMinFee, oldMaxFee, oldInsuranceShareBps, newFeeBps, newMinFee, newMaxFee, newInsuranceShareBps)`, or document the asymmetry. **Fixed in this sprint** — see commit attached.

#### I-V2-02 — Fee-on-transfer / rebasing tokens unsupported, undocumented

- **Location:** `createJob` lines 190-193, the H-05 fix.

- **Description:** The strict `received == amount` check (line 193) means any token that takes a transfer fee or rebases will permanently revert `createJob`. The contract is generic ERC20 in the constructor — anyone deploying V2 with a non-clean ERC20 will discover this only at first call.

- **Recommended fix:** add a NatSpec note in the contract header: "Only ERC20s without transfer-time fees or rebasing semantics are supported. USDC is the canonical target."

#### I-V2-03 — No view function exposing the invariant for off-chain monitors

- **Location:** `totalEscrowed` is a public state variable (auto-getter exists), but no helper returns both stored and actual side-by-side for off-chain assertion.

- **Recommended fix:** add:
  ```solidity
  function escrowInvariant() external view returns (uint256 stored, uint256 actual) {
      return (totalEscrowed, token.balanceOf(address(this)));
  }
  ```
  Trivial, no gas concern (view), simplifies monitoring.

#### I-V2-04 — NatSpec header claims approveAndPay enforces deadline; code doesn't

- **Location:** lines 16-17 of V2 NatSpec:
  > Enforces `block.timestamp <= deadline` in `submitResult` and `approveAndPay` (fixes H-03).

  vs. `approveAndPay` lines 235-238 where the check is explicitly commented out.

- **Description:** Documentation drift between the contract header (claims enforcement) and the code (deliberately disabled). Reviewer reads the header, expects strict enforcement, then sees the comment in the code and is confused / suspicious.

- **Recommended fix:** update the NatSpec header to say "Enforces `block.timestamp <= deadline` in `submitResult` (fixes H-03); `approveAndPay` accepts late approval as a deliberate UX choice — see M-V2-01 for the trade-off." **Fixed in this sprint.**

#### I-V2-05 — `dispute()` reason length limited to 256 bytes, error is generic `InvalidStatus`

- **Location:** `dispute` line 265:
  ```solidity
  if (bytes(reason).length > 256) revert InvalidStatus();
  ```

- **Description:** Reverting with `InvalidStatus` for an over-long reason string is misleading — the status was fine, the input was wrong.

- **Recommended fix:** add `error ReasonTooLong()` and use it. Cosmetic.

---

## 4. Backend Findings

These are findings in `apps/backend/src/agora_api/` paths that mediate between users and V2 on-chain calls.

### HIGH (operational, not contract-level)

#### B-V2-01 — Privy auth fails-open when PRIVY_APP_ID is empty

- **Location:** `apps/backend/src/agora_api/auth/privy.py` lines 129-137:
  ```python
  if not settings.privy_app_id:
      if token.startswith("agora-dev:"):
          privy_user_id = token.removeprefix("agora-dev:").strip()
          if not privy_user_id:
              raise PrivyAuthError("dev token missing privy user id")
          return {"sub": privy_user_id, "iss": "agora-dev", "aud": "agora-dev"}
      raise PrivyAuthError(
          "Privy auth not configured on this server (set PRIVY_APP_ID)"
      )
  ```

- **Description:** When `PRIVY_APP_ID` is empty (defaults to `""` in `config.py`), any client sending `Authorization: Bearer agora-dev:user-X` is accepted as user X. This is a deliberate dev/test hatch. It is gated by **the configuration not being set** rather than by **an explicit dev/test flag**.

  Today production has `PRIVY_APP_ID` set correctly in `/opt/agora/apps/backend/.env`. But config drift is a realistic threat: a future deploy that accidentally drops the variable would silently re-enable the bypass.

- **Impact:** Under deployment misconfiguration, an attacker can impersonate any user (including admins). Test of impact today: send `Authorization: Bearer agora-dev:user-admin-anyone` against the production API. With the production `.env` it returns 401; with an empty `PRIVY_APP_ID` it would succeed.

- **Recommended fix:** introduce an explicit `ALLOW_DEV_BEARER: bool = False` setting. The bypass requires that flag set to True regardless of `PRIVY_APP_ID`. Production `.env` should never set it; local dev / pytest can set it.

  Fail-closed by default.

### LOW

#### B-V2-02 — Webhook signature accepts future timestamps within ±max_age

- **Location:** `apps/backend/src/agora_api/webhooks/signing.py` line 128:
  ```python
  age = abs(int(time.time()) - ts)
  if age > max_age_seconds:
      raise SignatureInvalid(...)
  ```

- **Description:** The `abs()` allows timestamps up to 5 minutes in the FUTURE to verify. Most webhook implementations only accept past timestamps with a grace window.

- **Impact:** Marginal. An attacker who already has a valid signature for a future timestamp could replay it. Practically irrelevant because signatures are computed by the backend's signing key — the attacker would need to control that key, at which point they don't need to replay anything.

- **Recommended fix:** change to one-sided check: `now - ts < max_age` AND `ts <= now + small_clock_skew` (e.g. 30 seconds). Cosmetic but tidy. **Fixed in Sprint 39b** (commit `39585da`).

---

## 4b. Backend Findings — x402.py (Sprint 40 audit)

Read pass over the 926-line `apps/backend/src/agora_api/routes/x402.py` — the HTTP-402 escrow lifecycle endpoint. This is the central trust surface between agent clients and the V2 contract; every state change goes through here.

### HIGH (operationally)

#### X-A2 — Refund 402 instructions tell agents to call V1 `refund()` which doesn't exist on V2

- **Location:** `refund_x402_job` (line 739): `"function": "refund"` in the 402 payment-required dict.

- **Description:** The 402 response for `/v1/x402/jobs/{job_id}/refund` instructs the agent to call `AgoraEscrow.refund(jobId)`. On V2 this function does not exist — V2 split `refund` into `refundExpired()` (permissionless after deadline) and `resolveDispute()` (owner-only). Any agent that follows the 402 instructions against a V2 escrow will have their tx revert with "function selector not found."

- **Impact:** The agent-facing refund flow is functionally broken on V2 today. No funds are at risk — the escrowed USDC stays in V2, the deadline-elapsed clean-refund path is still possible (the agent can call `refundExpired` directly on Basescan or via SDK), but every agent that uses our recommended x402 flow will hit a revert.

  In practice no V2 job has yet needed refund (the only V2 job, 1d7c3dcd, settled cleanly), but this would block production at first refund attempt.

- **Recommended fix:** dispatch the function name based on `settings.escrow_abi_version`. **Fixed in Sprint 40** — see commit attached.

### MEDIUM

#### X-A1 — JobCreated event lookup in `/jobs` lacks the H-04 address filter

- **Location:** `create_x402_job` (lines 263-280, pre-fix): inline `for log_entry in receipt["logs"]:` loop that calls `client.escrow.events.JobCreated().process_log(log_entry)` without checking which contract emitted the log.

- **Description:** Every other lifecycle endpoint (/result, /approve, /refund, /dispute) uses the `_find_event()` helper, which has the H-04 audit fix: explicitly skip logs from contracts other than the configured escrow address. The /jobs endpoint missed this rewrite — it has its own inline loop.

  Attack: an attacker deploys a fake escrow contract on Base Sepolia, makes a tx that emits a `JobCreated` event with `(amount, taskHash, payee)` values matching what the agent's /jobs POST claims. The fake contract doesn't move any USDC into our real V2; the inline loop in /jobs matches the event by signature alone; the backend creates a Job row pointing to an `onchain_job_id` that lives only in the fake contract.

  Follow-on: the provider does the work. On /result the backend tries to verify a `ResultSubmitted` event on our real V2 for that `onchain_job_id` — which doesn't exist — and returns 402 "event missing." Provider has worked for free; no funds were ever actually escrowed.

- **Impact:** Adversarial provider-griefing primitive. Requires the attacker to spend gas (deploying + calling the fake contract) but not USDC. Severity bumped to MEDIUM because the work-loss is real and the attack is cheap.

- **Recommended fix:** replace the inline loop with `_find_event(receipt, client.escrow.events.JobCreated)`. **Fixed in Sprint 40** — see commit attached.

### LOW

#### X-A3 — `listing_id` parsed via `uuid.UUID(...)` twice

- **Location:** `create_x402_job` lines 191 and 292.

- **Description:** Same input parsed and validated twice — once before the 402 path is taken (to fetch the listing for `payee_wallet` resolution) and once after (to store as `listing_uuid` on the Job row). Cosmetic.

- **Recommended fix:** keep one parse; reuse the variable across the function body.

### INFORMATIONAL

#### X-A4 — `_find_event` log address normalisation is needlessly verbose

- **Location:** `_find_event` line 146:
  ```python
  log_addr = (log_entry.get("address") or "").lower() if hasattr(log_entry, "get") else (log_entry["address"].lower() if log_entry.get("address") else "")
  ```

- **Description:** Defends against `log_entry` being either a dict (has `.get`) or an `AttributeDict`. Web3.py 7.x always returns `AttributeDict` for receipts; the dual-path safety is no longer required. A `# noqa: E501` is required to keep the line under the 120-char limit.

- **Recommended fix:** simplify to `log_addr = (log_entry["address"] or "").lower()`. Cosmetic only.

---

## 4c. Backend Findings -- watcher.py (Sprint 41 audit)

Read pass over the 194-line `apps/backend/src/agora_api/chain/watcher.py` -- the background loop that reconciles on-chain state with the DB when agents bypass our /v1/x402 endpoints and talk to the escrow contract directly.

### MEDIUM

#### W-A1 -- Partial commit semantics: status update commits even if webhook enqueue fails

- **Location:** `_sweep_once` (lines 124-136) and `_reconcile_one` (lines 165-194).

- **Description:** `_reconcile_one` flushes the `job.status` change at line 166 _before_ enqueueing the two webhooks (one to requester, one to provider). The outer loop in `_sweep_once` catches per-job exceptions (line 129) and continues to the next job. At the end of the loop, if `any_change` is True, the session is committed (line 136) -- which includes the flushed-but-no-webhook-enqueued state from a partially-failed job.

  Result: the DB ends up with `status == completed` (say) but the corresponding `job.completed` webhook never reaches the agent. On the next sweep, the watcher's check `if target == job.status: return False` returns immediately because the status now matches -- so the webhook is permanently lost.

- **Impact:** Silent webhook loss under partial failure of `enqueue_for_agent`. Agent that's relying on the webhook to drive its own state machine (claim payment, retry result, etc.) never gets the signal.

- **Recommended fix:** wrap each `_reconcile_one` in a SAVEPOINT (`session.begin_nested()`) so failures roll back the whole job's changes including the status update. Or: do the enqueue BEFORE setting `job.status = target`, so a failure leaves the next sweep re-attempting from scratch.

#### W-A2 -- `onchain_job_id` was a `Decimal` in the webhook payload; default `json.dumps` cannot serialise it

- **Location:** `_reconcile_one` line 172-176 (pre-fix).

- **Description:** `job.onchain_job_id` is mapped to SQLAlchemy `Numeric(78, 0)` which materialises as Python `Decimal`. `enqueue_for_agent` writes the payload into the `webhook_deliveries` table's `JSON` column, which goes through `json.dumps`. The default encoder raises `TypeError: Object of type Decimal is not JSON serializable`. 

  In production today this path has never fired because the only completed V2 job (`1d7c3dcd`) was settled via `/v1/x402/jobs/{id}/approve`, which goes through `x402.py` and never touches the watcher's enqueue path. The first V2 job that completes via direct on-chain interaction (agent bypasses our API) would hit this.

- **Impact:** Watcher webhook delivery silently broken for direct-on-chain completions. Combined with W-A1 above, the silent breakage is impossible to detect from the API side -- the operator only finds out when an agent complains "I never got my completion webhook."

- **Recommended fix:** explicit cast to `int` in the payload. **Fixed in Sprint 41** -- see commit attached.

### LOW

#### W-A3 -- ~~Redundant~~ INTENTIONAL late import of settings inside `_sweep_once`

- **Location:** `_sweep_once` line 109 -- `from ..config import get_settings` inside the function body.

- **Description:** ~~Cosmetic. The late re-import was apparently added during the Sprint 36g hotfix and never cleaned up.~~ **Self-audit follow-up:** the late import is INTENTIONAL. It enables tests to patch `agora_api.config.get_settings` without having to know about (or re-patch) the binding in `agora_api.chain.watcher`. Sprint 41 "fixed" this by moving to the module-level import, which silently broke `test_sweep_filters_by_current_escrow_address` (CI #130 caught it). Reverted in Sprint 43-fix with an explanatory comment so future readers don't repeat the mistake.

- **Lesson:** "redundant late import" is a frequent false-positive when test code patches the wrong layer. Sprint 41's analysis was wrong; the audit doc retains it for transparency.

#### W-A4 -- No backoff between sweeps on consecutive RPC failures

- **Location:** `chain_watcher_loop` lines 89-93.

- **Description:** If the configured RPC URL is unreachable, every sweep raises an exception, gets caught at line 92, sleeps `interval` (5+ seconds), and retries. After N consecutive failures, the watcher should back off exponentially (cap at e.g. 5 min). Today it hammers the RPC at the configured interval forever.

- **Impact:** Operational only. Doesn't lose data; just generates log noise and a small load on the RPC endpoint. Not critical for testnet.

- **Recommended fix:** track consecutive-failure count; backoff `min(interval * 2**failures, 300)` until a successful sweep.

### INFORMATIONAL

#### W-A5 -- Race vs `x402.py`: two paths can both fire the same event

- **Location:** `_reconcile_one` (watcher) and `approve_x402_job` (x402.py line 666-676).

- **Description:** Both code paths can fire `job.completed` when the on-chain `JobApproved` event lands. Today the race is benign: the watcher's `if target == job.status: return False` check makes it a no-op once x402.py has updated the DB. But the two enqueues could in principle write two `webhook_deliveries` rows for the same `(job_id, event_type)` pair if they truly race (x402.py reads job.status=offered, decides to update; watcher reads chain status=Approved + DB status=offered, decides to update; both write).

  Postgres's per-row locks at flush time serialise the actual `UPDATE jobs SET status` writes, but the `INSERT INTO webhook_deliveries` rows are independent and would both commit.

- **Impact:** Possible duplicate webhook to the agent for one state change. Agents are expected to be idempotent in their handlers (the webhook contract says so), so impact is bounded.

- **Recommended fix:** add a `UNIQUE(job_id, event_type, status)` constraint on `webhook_deliveries` so a duplicate insert is caught at the DB layer. Or: at the application layer, check for an existing delivery before enqueueing.

#### W-A6 -- Sweep query was unbounded

- **Location:** `_sweep_once` lines 112-119 (pre-fix).

- **Description:** The SELECT had no LIMIT. If the watcher came back online after a multi-day outage with thousands of stale jobs, a single sweep could spend several minutes blocking subsequent ones (each job is an RPC roundtrip).

- **Impact:** Operational. Today there are ~5-10 live V2 jobs at any time so the issue is hypothetical. But a single bad RPC + thousands of stale jobs is a real DoS surface for ourselves.

- **Recommended fix:** add `.limit(1000).order_by(Job.created_at.asc())` so worst-case sweep is bounded. **Fixed in Sprint 41**.

#### W-A7 -- get_job() is sequential per job, not batched via multicall

- **Location:** `_reconcile_one` line 145.

- **Description:** N live jobs = N sequential RPC roundtrips per sweep. Currently fine because N is small (single-digit V2 jobs). At 100+ jobs it becomes the dominant latency source.

- **Recommended fix:** add a `batch_get_job(job_ids)` to `AgoraEscrowClient` that uses multicall3 or a custom batch contract. Out of scope for testnet practice; flag for mainnet.

---

## 4d. Backend Findings -- rfq.py (Sprint 43 audit)

Read pass over the 514-line `apps/backend/src/agora_api/routes/rfq.py` -- the RFQ (Request for Quote) marketplace endpoint suite (Sprint 31 + 34a/b for buyer signatures + 36d/e for replay protection and losing-bid lifecycle).

### LOW

#### R-A1 -- `_require_fresh_timestamp` window was symmetric, accepting future timestamps

- **Location:** `_require_fresh_timestamp` (lines 130-140, pre-fix). Same pattern as the B-V2-02 webhook timestamp finding, replicated here in the RFQ signed-payload validation.

- **Description:** `abs(now - ts) > timedelta(seconds=120)` accepted timestamps up to 120s in the future. An attacker who briefly captured a buyer's signed payload (e.g. via a passive MITM during signing) could replay it up to 2 minutes later, extending the practical replay surface beyond the intent of a freshness window.

- **Impact:** Marginal. Defence-in-depth posture is worth tightening because RFQ signed payloads are higher-stakes than webhook signatures (they bind a buyer to a price commitment).

- **Recommended fix:** one-sided window: reject anything older than 120s, OR more than 30s in the future. **Fixed in Sprint 43** -- see commit attached.

#### R-A2 -- `_verify_agent_signature` had a broad `except Exception` clause that masked server-side errors

- **Location:** `_verify_agent_signature` (lines 238-249, pre-fix).

- **Description:** The outer `except Exception` at line 248 caught all errors -- including programmer errors like `KeyError`, `TypeError`, broken `did_document` parsing -- and surfaced them as 400 "signature invalid". A real signature-mismatch error was indistinguishable from a malformed-DID-document server bug, hampering debugging and giving attackers no useful error signal but also hiding real issues from operators.

- **Recommended fix:** catch only `nacl.exceptions.BadSignatureError` (the actual "wrong signature" case) and `binascii.Error` (the base64 case). Let everything else propagate as 500. **Fixed in Sprint 43**.

### MEDIUM (operational, not fixed in this sprint)

#### R-A3 -- Race condition between `count_bids_*` and `create_bid` flush

- **Location:** `create_bid` (lines 389-395 + 408).

- **Description:** The endpoint checks `count_bids_for_request(...) >= MAX_BIDS_PER_REQUEST` and `count_bids_for_provider(...) >= MAX_BIDS_PER_AGENT_PER_REQUEST` at the application layer, then inserts a new bid row at line 408. Two concurrent `/bids` POSTs can both observe `N < MAX`, both pass, both insert -- ending up at `N + 2`.

- **Impact:** Soft-limit violations only. MAX_BIDS_PER_REQUEST=50 and MAX_BIDS_PER_AGENT_PER_REQUEST=3 are anti-spam limits, not security boundaries. Exceeding by 1-2 is harmless but inelegant.

- **Recommended fix:** rely on DB-level uniqueness instead of application-layer counts. Add `UNIQUE(request_id, provider_did, sequence)` with a per-provider sequence column, OR use `SELECT ... FOR UPDATE` to serialise the count-then-insert. Operational improvement, not security-critical.

#### R-A4 -- Race between concurrent `create_bid` and `accept_bid` can leave dangling `pending` bid

- **Location:** `create_bid` (line 368 status check) vs `accept_bid` (line 485 `rfq_repo.accept_bid` which sets request to accepted + losing-bids to rejected).

- **Description:** `create_bid` reads `req.status == open` at line 368. If `accept_bid` for the same request commits between this read and our INSERT, our new bid lands attached to a now-accepted request. Sprint 36e's losing-bid sweep already ran and didn't include our new bid (it's not yet inserted at that point), so the new bid stays at `pending` status forever on an already-closed request.

- **Impact:** Dangling pending bid on an accepted request. Not exploitable but confusing for the bidding agent who's holding signed resources expecting they might still win.

- **Recommended fix:** add `WHERE request.status = 'open'` to the INSERT predicate, OR re-check status at flush time and revert if changed. Cleaner: switch to a transactional pattern where accept_bid takes an advisory lock that create_bid respects.

### INFORMATIONAL

#### R-A5 -- `deadline` not coerced to UTC-aware in `CreateRequestBody`

- **Location:** `CreateRequestBody.deadline` (line 57) and uses at line 199 + 304.

- **Description:** Same shape as the Sprint 34f bid.expires_at fix and the Sprint 36f create_bid.expires_at fix. A buyer sending a naive datetime in `deadline` will have `deadline.isoformat()` produce a no-tz string that the server signs against; later comparisons against `datetime.now(UTC)` would raise TypeError if the field were ever consumed in that pattern. Today nothing in `create_request` compares `deadline` to "now", so the bug doesn't surface -- but it's a tz-aware footgun waiting for a future sprint to step on.

- **Recommended fix:** coerce in the model validator OR at use-site. Same pattern as Sprint 34f / 36f. Pre-emptive hygiene.

---

## 4e. Backend Findings -- escrow.py (Sprint 44 audit)

Read pass over the 538-line `apps/backend/src/agora_api/chain/escrow.py` -- the `AgoraEscrowClient` that wraps V1/V2 dispatch via web3.py. Sprint 36c established the explicit version dispatch; this audit re-examines it adversarially.

### MEDIUM (operational, documented not fixed)

#### E-A2 -- `_send_tx` uses hardcoded gas + fee parameters that will fail on mainnet

- **Location:** `_send_tx._build_and_send` (lines 482-491). Hardcoded `gas=500_000`, `maxFeePerGas=0.1 gwei`, `maxPriorityFeePerGas=0.01 gwei`.

- **Description:** Base Sepolia gas prices are typically <0.01 gwei so 0.1 gwei is fine. Base mainnet routinely sees 0.1-1 gwei base fee, with priority sometimes 0.01-0.1 gwei. The hardcoded 0.1 gwei maxFeePerGas would be at or below mainnet base fee, causing every settler tx to be rejected. The hardcoded 500_000 gas limit is generous but also static -- if a future contract path needs more, settler txs revert.

- **Impact:** Settler-broadcast paths break on mainnet. Today the only such path was `settler_create_job` which is now removed (E-A8); but if any new owner-only Safe-Tx-via-settler flow appears, it'll inherit this issue.

- **Recommended fix:** read fee params from `w3.eth.fee_history` or `w3.eth.gas_price` and apply a configurable multiplier. Cap via settings. Defer until a real settler-broadcast caller exists.

#### E-A3 -- Settler private key held in plaintext process memory

- **Location:** `__init__` line 346: `self.settler = self.w3.eth.account.from_key(settler_pk) if settler_pk else None`.

- **Description:** The settler private key is loaded from `.env` and held in plaintext memory of the running process. A process dump, debugger attach, or container-level snapshot could recover it. For testnet practice this is acceptable; for mainnet a hardware-wallet or KMS-based signer would be the right answer.

- **Impact:** Single-host compromise of agora-1 reveals the settler key. Today the settler EOA's only authority on-chain is whatever the Safe hasn't already replaced -- the V2 contract is owned by the Safe, the settler isn't an admin. The settler is just the "pay gas for Safe txs" relayer. So worst case is the attacker pays gas for arbitrary safe-or-V2 calls, which they'd have to construct themselves -- they can't drain anything.

- **Recommended fix:** before mainnet, replace plaintext settler key with a remote signer (Web3Signer, AWS KMS, etc.). Document the threat model.

#### E-A5 -- Nonce read-then-use race in concurrent `_send_tx` calls

- **Location:** `_send_tx._build_and_send` line 482: `nonce = self.w3.eth.get_transaction_count(self.settler.address)`.

- **Description:** Two concurrent `_send_tx` calls will both call `get_transaction_count` and may both observe the same `nonce` value (the second call's tx is broadcast before the first one is mined and visible to the node's mempool). The second tx is then rejected by the node with a "nonce too low / already used" error.

- **Impact:** Operational only. The caller gets a clear error from `send_raw_transaction` and can retry. Today the backend rarely issues concurrent settler txs because the only path that uses the settler-broadcast pattern is `settler_create_job` (just removed in E-A8). If a new high-concurrency settler path appears, this becomes real.

- **Recommended fix:** local nonce cache that increments after broadcast; on tx failure, reset from chain.

### LOW

#### E-A4 -- `get_job` accesses tuple by index, fragile against ABI changes

- **Location:** `get_job._read` lines 360-369.

- **Description:** `result[0]` through `result[6]` indexed access. V2's 11-tuple is correctly handled by only reading the first 7, but if a future V3 reorders fields (e.g. inserts `creationBlock` at position 2) every field's index shifts and `get_job` silently extracts the wrong values into the wrong `OnchainJob` fields.

- **Impact:** Hypothetical future-V3 bug. Not exploitable today.

- **Recommended fix:** decode by field name. If web3.py returns a named tuple for struct-returning functions, use `result.payer`, `result.payee`, etc.

### INFORMATIONAL

#### E-A6 -- No assertion that RPC's chain_id matches settings.chain_id

- **Location:** `__init__` -- pre-fix, no chain_id check.

- **Description:** If `settings.rpc_url` points at a different chain than `settings.chain_id` claims (config drift, copy-paste error, Anvil left running on chain 31337), every signed tx is signed with the wrong chain_id and either reverts at the destination or, more dangerously, becomes a valid tx on the chain the RPC actually serves.

- **Recommended fix:** check at construction and either fail-loud or warn-loud. **Fixed in Sprint 44** -- warn-only because failing construction blocks the entire backend boot on a transient RPC failure; warn lets the next `send_tx` raise its own error.

#### E-A8 -- Dead code: `settler_create_job` and `_extract_job_id`

- **Location:** Pre-fix lines 446-471 and 500-508.

- **Description:** Implemented for a never-realised settler-broadcast createJob path. The actual x402 /jobs flow has the agent broadcast and the backend just verifies the receipt (via the much safer `_find_event` helper). Dead code in a security-sensitive file is audit-noise that can mislead reviewers.

- Also: `_extract_job_id` had the same missing H-04 escrow-address filter that we just fixed in x402.py (X-A1) -- it accepted any `JobCreated` event in the receipt regardless of which contract emitted it. Removing it closes that gap too.

- **Recommended fix:** delete both. **Fixed in Sprint 44** -- restore from git if a real settler-broadcast caller appears.

---

## 5. What this self-audit did NOT cover

To set expectations honestly:

- **`apps/backend/src/agora_api/routes/x402.py`** (926 lines) — the HTTP-402 endpoint that sits between users and on-chain calls. Read the docstring + first 120 lines only. Should be audited end-to-end for receipt verification, idempotency under replay, and DB-vs-chain consistency.
- **`apps/backend/src/agora_api/routes/rfq.py`** (514 lines) — Sprint 31 RFQ marketplace. Sprint 34a/b added buyer signatures; Sprint 36d added signed_actions replay protection; Sprint 36e closed losing-bid lifecycle. Not re-read for this self-audit; relies on its dedicated test suite.
- **`apps/backend/src/agora_api/chain/watcher.py`** (194 lines) — the chain reconciliation loop. The known issue (mount-lag truncation, Sprint 36) was caught at the lint layer. Sprint 36g's filter is correct based on the test suite, but the watcher's drift-detection semantics for partial-confirmation scenarios were not re-examined here.
- **Gas / optimisation review** of V2 — not done. Tests pass, that's it.
- **MEV / sandwich-attack analysis** at deadline boundaries — partially considered in H-03 / M-V2-02 but not exhaustively.
- **Cross-contract reentrancy** between V2 and the agent's payee callbacks — V2 uses `safeTransfer` to push tokens; receiving contracts have no callback path on standard ERC20, so this is fine, but if a payee is a smart contract holding `onERC20Receive` semantics (non-standard), behaviour is undefined.

External reviewers are explicitly invited to dig into these areas.

---

## 6. Decisions taken alongside this audit

The trivial findings — **L-V2-01, I-V2-01, I-V2-04, I-V2-05** — are fixed in the same sprint commit as this document. They don't require external review because they're naming / event-shape / NatSpec changes with no semantic impact.

**The MEDIUM findings (M-V2-01, M-V2-02) and the backend HIGH (B-V2-01) are NOT fixed in this sprint.** They are surfaced for external reviewer comment. The operator (Andreas) will decide on fix shape after at least one external reviewer has weighed in, since the right answer touches the protocol's dispute-resolution UX and the deployment configuration story.

In the meantime:
- M-V2-01 / M-V2-02 mitigated operationally: the project documents that mainnet is gated on this, see [`TIMELOCK_DESIGN.md`](TIMELOCK_DESIGN.md) §9 open items.
- B-V2-01 mitigated by: production deploy has the correct `PRIVY_APP_ID`, verified via `V2_LIVE_STATE.md` (production env shows the correct setting). Drift detection should be added in a future Sprint.

---

_See [`EXTERNAL_REVIEW_REQUEST.md`](EXTERNAL_REVIEW_REQUEST.md) for how to submit findings._
_See [`TIMELOCK_DESIGN.md`](TIMELOCK_DESIGN.md) for the planned hardening of admin-key risk._
_See [`V2_LIVE_STATE.md`](../apps/backend/docs/V2_LIVE_STATE.md) for the live state of V2 today._

---

## 7. Sprint 45 -- Timelock landing (Option B)

**Date:** 2026-06-06
**Status:** code + tests + runbooks landed; on-chain deploy + ownership flip remain.

`contracts/TIMELOCK_DESIGN.md` Option B is implemented:

- `contracts/script/DeployTimelock.s.sol` -- deploys an OpenZeppelin
  `TimelockController` with `minDelay=86400`, Safe as proposer + canceller +
  executor, no external admin.
- `contracts/test/TimelockController.t.sol` -- 11 forge tests:
  role assignment, no-external-admin invariant, 24h minDelay, schedule→wait→execute
  happy path on `setFees`, cancel removes pending proposal, attacker cannot
  schedule, attacker cannot execute after Safe scheduled, V2 ownership flip
  simulated, `pause()` confirmed to require the 24h delay (Option B's documented
  operational cost).
- `experiments/timelock/` -- three runbooks:
  - `RUNBOOK_DEPLOY.md` -- deploy + post-deploy verification of all 5 role/delay
    invariants before any ownership transfer.
  - `RUNBOOK_OWNERSHIP_FLIP.md` -- the two-phase `transferOwnership` →
    schedule(`acceptOwnership`) → 24h → execute flow.
  - `RUNBOOK_PERMANENT_PAUSE_QUEUE.md` -- the rolling pre-queued pause that
    mitigates Option B's 24h pause delay.

### Known regressions introduced by Option B

| Function | Before Sprint 45 | After Sprint 45 | Mitigation |
|---|---|---|---|
| `pause()` | Safe-direct, instant | Timelock-scheduled, 24h delay | Rolling pre-queued pause (`RUNBOOK_PERMANENT_PAUSE_QUEUE.md`) |
| `unpause()` | Safe-direct, instant | Timelock-scheduled, 24h delay | Acceptable; deliberate restart should be slow |
| `resolveDispute(jobId, ...)` | Safe-direct, instant | Timelock-scheduled, 24h delay | **NOT acceptable for Mainnet.** TIMELOCK_DESIGN.md §5 flags this as a V2.1 candidate. For Sepolia testnet practice: acceptable. |
| `setFees`, `setFeeRecipient`, `setInsurancePool`, `transferOwnership` | Safe-direct, instant | Timelock-scheduled, 24h delay | Intended; no mitigation needed. |

### What is NOT addressed by Sprint 45

- Mainnet readiness for `resolveDispute`. TIMELOCK_DESIGN.md §5 still
  recommends V2.1 contract changes (oracle / 2-of-3 arbitrator pattern)
  before going to Mainnet.
- Automation of the rolling pause refresh. For Sepolia this is a manual
  on-call task. Mainnet should automate or replace it.
- The Timelock has not been audited by an external party in this sprint.
  The OZ TimelockController itself is widely deployed and audited; the
  configuration (proposers, executors, delay) is what the new test suite
  validates.

### Live state once `RUNBOOK_OWNERSHIP_FLIP.md` lands

After both phases of the ownership flip, the on-chain control chain is:

```
Safe 2-of-2 (0x8Ec6...)
  --[ proposer + canceller + executor ]-->  TimelockController (new)
                                              --[ owner ]-->  AgoraEscrowV2 (0x0e8E...)
```

This file's `Owner:` header at the top of §1 will be updated to point at the
Timelock once the flip lands.

