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
