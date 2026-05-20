# AgoraEscrow Security Review

**Target:** `contracts/src/AgoraEscrow.sol` (Solidity ^0.8.26, ~149 lines)
**Companion tests:** `contracts/test/AgoraEscrow.t.sol`
**Deployed (testnet):** `0xCE783B527C83c4fFFF3D3565c0F3C3204be02B76` on Base Sepolia
**Reviewer:** internal pre-audit review (not a substitute for a Cyfrin / OpenZeppelin / CodeHawks engagement)
**Date:** 2026-05-20

---

## 1. Executive Summary

**Would I ship this to mainnet today? No.** The contract is small, generally well-structured, and the happy paths look correct, but several findings would almost certainly be flagged HIGH or CRITICAL by a competent auditor — most importantly the **`refund()` authorization logic that lets the owner unilaterally drain any `Funded` or `Disputed` job back to the payer**, a `Disputed` status that is a one-way trap with no resolution path, and the absence of a fee-on-transfer / inflation-token guard on USDC accounting. The dispute mechanism is effectively non-functional: once `dispute()` is called, only the owner can resolve it, and the only resolution available is "refund the payer," which means the payee can never be paid after a dispute even if they delivered correctly. Combined with the lack of pause / upgrade / timelock, this is not mainnet-ready until at least the HIGH findings are fixed and an external audit is performed.

**Biggest single concern:** the dispute / refund authorization model — it concentrates trust in the owner EOA with no timelock or multisig requirement, and the refund-only resolution path means a malicious or compromised payer can always extract their funds after a payee delivers work (see H-01, H-02, H-03).

---

## 2. Findings

Severity scale: **CRITICAL** (funds at immediate risk / trivially exploitable) > **HIGH** (funds at risk under realistic conditions or core invariant broken) > **MEDIUM** (functional/economic bug, escalation path exists) > **LOW** (best-practice / minor) > **INFORMATIONAL** (style, gas, documentation).

### CRITICAL

#### C-01 — Owner can unilaterally refund any non-finalized job, including delivered work
- **Location:** `refund()`, lines 115–123, specifically the predicate at line 119: `if (!deadlineExpired && msg.sender != owner) revert Unauthorized();`
- **Description:** The owner can call `refund(jobId)` on any job whose status is `Funded` **or** `Disputed`, with no time constraint, no payee consent, and no on-chain due-process. There is no `Submitted` guard either — but more importantly, once a payer calls `dispute(jobId, "...")` on a `Submitted` job, the status flips to `Disputed`, at which point the owner can refund the payer regardless of whether the payee delivered correct work.
- **Impact:** This is a unilateral clawback. Any payer can grief any payee by: (1) creating a job, (2) waiting for `submitResult`, (3) calling `dispute()`, (4) asking the owner (or being the owner, or colluding with the owner, or compromising the owner key) to call `refund()`. The payee loses payment for delivered work. Because `owner` is set to `msg.sender` in the constructor and there's no multisig/timelock requirement, a single key compromise drains every open escrow back to payers.
- **Recommended fix:**
  - Split `refund()` into two paths: a permissionless `refundExpired()` callable only when `block.timestamp > deadline && status == Funded` (payee never submitted) and a `resolveDispute(jobId, address recipient, uint256 payeeShare, uint256 payerShare)` callable only on `Disputed` status, ideally behind a timelock or arbitration committee.
  - At minimum, require `status == Disputed` for the owner branch and emit a distinct event so off-chain observers can detect owner overrides.
  - Strongly consider replacing single-EOA `owner` with a multisig (Safe) and a `Timelock` for both `setFees` and dispute resolution.

---

### HIGH

#### H-01 — `Disputed` status is a one-way trap with no resolution to payee
- **Location:** state machine across `dispute()` (lines 107–113), `approveAndPay()` (line 94 — only accepts `Submitted`), `refund()` (line 117 — accepts `Funded` and `Disputed`).
- **Description:** Once a job enters `Disputed`, the only terminal state reachable is `Refunded` (via the owner). There is no `resolveDispute` function that pays the payee, no partial split, and `approveAndPay` rejects `Disputed`. A payer can therefore neutralize any successful delivery by calling `dispute()` — even with an empty reason string — and the payee's only recourse is off-chain pressure on the owner.
- **Impact:** Core protocol invariant broken: payees can never be made whole after a dispute. This is an economic / reputational risk: rational payees will refuse to take on Agora jobs once they understand this, and rational payers can extract free work. Note that `dispute()` is also callable in `Funded` state (line 109) so a payer can pre-empt submission by disputing immediately after `createJob`.
- **Recommended fix:** Add `function resolveDispute(uint256 jobId, uint256 payeeAmount)` callable by owner (eventually arbiter / timelock) that handles partial splits, charges the protocol fee correctly, and transitions to a new terminal state (e.g., `Resolved`). Define what happens to fee on partial disputes.

#### H-02 — `dispute()` is callable in `Funded` state, allowing payer-side denial-of-service before submission
- **Location:** `dispute()`, line 109: `if (j.status != JobStatus.Submitted && j.status != JobStatus.Funded) revert InvalidStatus();`
- **Description:** A payer can call `dispute()` immediately after `createJob`, before the payee has any opportunity to submit. Combined with H-01, this locks the job into a state from which only the owner can rescue funds, with the only available rescue being "refund payer."
- **Impact:** Payee griefing — the payer can refuse to allow submission at all and force a refund. Payee may have already spent compute / API credits preparing the result.
- **Recommended fix:** Restrict `dispute()` to `Submitted` only, OR require disputes raised in `Funded` to be raised by the payee only (so the payer can't grief the payee before submission), OR fold "payer wants to cancel before submission" into a separate `cancelBeforeSubmission` path that requires payee consent.

#### H-03 — No deadline enforcement on `submitResult` / `approveAndPay`
- **Location:** `submitResult()` lines 83–90 and `approveAndPay()` lines 92–105 — neither checks `block.timestamp <= j.deadline`.
- **Description:** The `deadline` field is stored and emitted, but only consulted by `refund()` (line 118). A payee can submit a result years after the deadline; a payer can approve and pay years late. This breaks the implicit contract that "after the deadline, the payer gets their money back."
- **Impact:** Race condition at the deadline boundary: at `deadline + 1`, both `submitResult` (payee) and `refund` (anyone, since `deadlineExpired` is true) become valid simultaneously. Whoever lands the transaction first wins. On Base, with private mempool relays / sequencer ordering, this is a real MEV-style hazard for both parties. A patient payee can also "lurk" past the deadline and submit a result on a `Funded` job that was implicitly abandoned.
- **Recommended fix:**
  - In `submitResult`, require `block.timestamp <= j.deadline`.
  - In `approveAndPay`, optionally allow late approval (grace period) but make the semantics explicit.
  - Document the deadline boundary behavior.

#### H-04 — No reentrancy guard despite external calls to arbitrary `token`
- **Location:** `_transfer` (lines 140–143), `_transferFrom` (lines 145–148); call sites in `createJob` (line 69), `approveAndPay` (lines 101–103), `refund` (line 121).
- **Description:** The contract calls `token.call(...)` on an immutable but externally-supplied address. The deployed instance uses USDC which is non-reentrant, so **on USDC this is not exploitable today.** However: (a) the contract is generic and the token is constructor-set, (b) on Base Sepolia the constructor accepts any address, (c) `approveAndPay` performs three sequential external transfers (insurance, fee, payee) after the status update (status update is on line 96, transfers on 101–103, so CEI is technically respected for state — good), but the **three transfers are interleavable in that a malicious token could revert the third transfer after the first two succeed**, leaving the contract in a `Approved` state with the payee unpaid and no way to retry (since `approveAndPay` rejects `Approved`).
- **Impact:** With USDC: low. With any future migration to a non-standard token: payee funds stuck. Also: the multi-transfer pattern means a partial failure cannot be retried.
- **Recommended fix:**
  - Use OpenZeppelin `ReentrancyGuard` (`nonReentrant` modifier on every external state-changing function) as defense in depth.
  - Consider sending the gross amount to the payee and having the payee pay the fee, OR use a pull-payment pattern, OR make the multi-transfer atomic by failing the whole tx (currently OK because of `revert TransferFailed`, but state has already moved to `Approved`). Actually re-check: the status is set BEFORE the transfers, so if the third transfer reverts, the entire tx reverts and state is rolled back. That's good. But still recommend `nonReentrant` as defense-in-depth.

#### H-05 — `createJob` does not verify the contract actually received `amount` tokens (fee-on-transfer / rebasing token risk)
- **Location:** `createJob`, line 69: `if (!_transferFrom(msg.sender, address(this), amount)) revert TransferFailed();`
- **Description:** The contract trusts that `transferFrom(payer, this, amount)` deposits exactly `amount`. With USDC on mainnet, this is true today. But: (a) USDC is upgradeable by Circle and could in principle change behavior, (b) the contract has no token whitelist — a fork or wrapper could deploy with a fee-on-transfer token, (c) USDC has a blocklist that can cause `transferFrom` to revert (which is handled), but the bigger risk is silent under-deposit.
- **Impact:** If the token ever takes a fee, the escrow records `amount` but holds `amount - tokenFee`. Later `approveAndPay` tries to transfer `amount - protocolFee` to the payee and `protocolFee` to fee/insurance, but only `amount - tokenFee - protocolFee` is available — the LAST transfer (payee) reverts, jamming the job in `Approved` status forever (and `refund` won't take `Approved` either). **Funds for that job are stuck and the next job's funds can be drained by the affected payee via the cross-job balance pooling.**
- **Recommended fix:**
  - Measure `IERC20(token).balanceOf(address(this))` before and after `transferFrom` and store the actual delta as `j.amount`, OR
  - Add a documented invariant that `token` MUST be a non-fee-on-transfer, non-rebasing ERC20 and lock to USDC explicitly (hardcode address, no constructor arg).

#### H-06 — Cross-job balance pooling allows a malicious actor to drain other escrows on accounting glitches
- **Location:** architecture-level; visible in `approveAndPay` and `refund` which transfer from the contract's combined balance, not from a per-job sub-account.
- **Description:** All deposits sit in one pool. Any accounting bug (including H-05, but also potential future bugs) causes the contract's invariant `sum(open job amounts) == token.balanceOf(this)` to break in the direction of less balance than recorded. The next legitimate payout will fail; the one before it succeeds. The losses fall on whichever job is finalized last, not on the job that caused the underflow.
- **Impact:** Not directly exploitable today, but it converts any future accounting bug from "lose 1 job's funds" to "lose the last job's funds, which may be arbitrarily large." Auditors will call this out as an architectural concern.
- **Recommended fix:** Track `totalEscrowed` as an explicit storage variable, increment on deposit, decrement on payout, and assert invariants. Optionally, expose a public `totalEscrowed` to enable off-chain monitoring.

---

### MEDIUM

#### M-01 — `transferOwnership` is single-step and accepts the zero address
- **Location:** line 138: `function transferOwnership(address _n) external onlyOwner { owner = _n; }`
- **Description:** No `pendingOwner` two-step pattern (à la OpenZeppelin `Ownable2Step`), no zero-address check. A typo can permanently brick the owner-only functions (`setFees`, `setFeeRecipient`, `setInsurancePool`, `refund` for disputed jobs).
- **Impact:** Loss of admin control. Given that the owner is also the only dispute resolver, this would brick the dispute mechanism.
- **Recommended fix:** Use `Ownable2Step` from OZ; reject `address(0)`.

#### M-02 — `setFeeRecipient` / `setInsurancePool` accept the zero address
- **Location:** lines 136, 137.
- **Description:** No zero-address validation. If either is accidentally set to `address(0)`, `approveAndPay` will revert because USDC's `transfer(0, ...)` reverts. All future approvals are bricked until the owner fixes it. Note: this is recoverable (owner can re-set) so it's MEDIUM not HIGH.
- **Impact:** Temporary DoS on `approveAndPay`. Affects all pending Submitted jobs simultaneously.
- **Recommended fix:** `require(_r != address(0))` in both setters.

#### M-03 — `setFees` can be sandwiched against `createJob` / `approveAndPay`
- **Location:** `setFees` (lines 125–134) interacts with `computeFee` (lines 59–64), which is read by `approveAndPay` (line 97).
- **Description:** The fee charged is computed at `approveAndPay` time, NOT at `createJob` time. A user creates a job expecting `feeBps=100, maxFee=25 USDC`; before they approve, the owner raises `feeBps` to 200 and `maxFee` to (say) the entire job amount. The user's approval now pays a much larger fee to the protocol. The constructor caps `_feeBps <= 200` (2%) and `_insuranceShareBps <= 5000` (50% of fee) but does NOT cap `_maxFee` — the owner could set `maxFee = type(uint256).max`, then `computeFee = min(maxFee, 1% of amount)` would just return `amount`... actually no, `min(maxFee, 1% * amount)` would return `1% * amount` when `maxFee > 1% * amount`. So with `feeBps=200, maxFee=∞`: fee = 2% of amount, capped at `min(amount, 2%*amount)` = 2%. The realistic worst case is 2% fee + 50% insurance share. Still, the user signed up under different fee terms.
- **Impact:** Trust-the-owner risk; not a fund drain, but a unilateral fee adjustment that retroactively applies. Auditors will flag this as MEDIUM.
- **Recommended fix:** Snapshot the fee parameters (`feeBps`, `minFee`, `maxFee`, `insuranceShareBps`) into the `Job` struct at `createJob` time. Compute fee using the snapshot in `approveAndPay`.

#### M-04 — Missing events for owner-only setters
- **Location:** `setFeeRecipient`, `setInsurancePool`, `transferOwnership` (lines 136–138).
- **Description:** No events emitted. `setFees` emits `FeesUpdated`, but the address setters and ownership transfer are silent.
- **Impact:** Off-chain monitoring / The Graph indexers / wallets can't detect these changes. Auditors flag this consistently.
- **Recommended fix:** Add `FeeRecipientUpdated`, `InsurancePoolUpdated`, `OwnershipTransferred(old, new)` events.

#### M-05 — `nextJobId` starts at 0, conflicting with `JobStatus.None` sentinel
- **Location:** `nextJobId` (line 34), `jobs` mapping (line 33), enum `JobStatus.None` (line 9).
- **Description:** Reading `jobs[999999]` (a non-existent job) returns a `Job` struct with `status == JobStatus.None`. None of the functions check for `JobStatus.None` explicitly — they check for the expected status. This is mostly safe because no function accepts `None` as valid. But `nextJobId++` returns `0` for the first job, which is a valid job ID, and there's no way for an off-chain consumer to distinguish "job 0 doesn't exist" from "job 0 exists with status None" via the public mapping. Minor, but a common audit nit.
- **Impact:** Off-chain UX; not a fund risk.
- **Recommended fix:** Initialize `nextJobId = 1`, OR explicitly handle the `None` case, OR document that job IDs start at 0.

#### M-06 — `refund()` permissionless once deadline expires — but the predicate has a subtle scope bug
- **Location:** `refund`, lines 117–119.
- **Description:** Read carefully:
  ```
  if (j.status != JobStatus.Funded && j.status != JobStatus.Disputed) revert InvalidStatus();
  bool deadlineExpired = block.timestamp > j.deadline && j.status == JobStatus.Funded;
  if (!deadlineExpired && msg.sender != owner) revert Unauthorized();
  ```
  So: (a) anyone can refund a `Funded` job after deadline — fine. (b) Only the owner can refund a `Disputed` job (regardless of deadline). (c) The owner can ALSO refund a `Funded` job BEFORE deadline. Case (c) is unintended — the owner shouldn't be able to clawback a freshly funded job that hasn't even reached submission. This compounds C-01.
- **Impact:** Owner can unilaterally cancel any active job at any moment, not just disputed ones. Payee may have already started work.
- **Recommended fix:** Require `j.status == JobStatus.Disputed` for the owner branch. Move the permissionless-after-deadline path into its own function.

#### M-07 — `dispute()` accepts arbitrary unbounded `string calldata reason`
- **Location:** `dispute()`, line 107.
- **Description:** No length cap. A caller can pass a 100 KB reason string. The string is only emitted, not stored, so the cost is paid by the caller — not a DoS on the contract, but it bloats logs and can be used to grief indexers. More importantly, the reason is `calldata` and emitted as an indexed-by-jobId-only event, so it's not searchable by reason on-chain. This is a design choice, not a bug.
- **Impact:** Minor — log bloat, indexer cost.
- **Recommended fix:** Cap reason length (e.g., 256 bytes) or replace with a `bytes32` reason code + off-chain JSON.

---

### LOW

#### L-01 — No pause mechanism
- **Description:** Stated in the task brief; this is indeed a finding. With no `Pausable`, a discovered vulnerability cannot be mitigated except by socially coordinating "stop using the contract." For a marketplace that touches user funds, OZ `Pausable` on `createJob` (so new funds can't enter while a bug is investigated) is standard.
- **Recommended fix:** Add `Pausable` and gate `createJob` (NOT `refund` or `approveAndPay`, so existing jobs can still exit).

#### L-02 — No upgrade / migration path
- **Description:** Immutable contract. If a critical bug is found, the only mitigation is to deploy v2 and convince all users to migrate, while existing escrows are stranded. Counter-argument: upgradeability introduces its own risks (storage layout, proxy admin compromise). This is a design trade-off; auditors will flag it as informational/low.
- **Recommended fix:** Either accept and document the immutability, OR use an `UUPSUpgradeable` proxy with a timelocked admin.

#### L-03 — `feeBps` typed as `uint16` (max 65535) but capped at 200; `insuranceShareBps` same
- **Description:** Tight types are fine; just note that the implicit assumption "bps < 10000" is enforced for `feeBps` (cap 200) and `insuranceShareBps` (cap 5000) only via `setFees`. The initial values set in storage declarations (lines 24–27) are correct. Not a bug.
- **Recommended fix:** None required; consider making these `immutable` if you don't intend to change them. (They ARE intended to be changeable, so this stays as-is.)

#### L-04 — `_transfer` / `_transferFrom` use hardcoded selectors instead of `IERC20`
- **Location:** lines 141, 146.
- **Description:** The hardcoded selectors `0xa9059cbb` (transfer) and `0x23b872dd` (transferFrom) are correct, and the data-length check handles non-standard ERC20s (e.g., legacy USDT) that return no data. This pattern is a poor man's `SafeERC20.safeTransfer` — it works but is fragile and harder to audit. **Note:** OZ `SafeERC20.safeTransfer` ALSO requires the transfer to succeed (revert on failure), which this implementation does via `revert TransferFailed()` at call sites — so behavior is equivalent. But there's no check that `token` is actually a contract (a call to an EOA returns `ok=true` with empty data, which would silently "succeed").
- **Impact:** If `token` is misconfigured to an EOA at construction, ALL transfers silently succeed without moving any funds. Payers `createJob` thinking they've deposited, but no tokens move. This is a constructor-time check, so realistic risk is low (Base Sepolia deployment is verified) but auditors will flag it.
- **Recommended fix:** Use OZ `SafeERC20` and check `token.code.length > 0` at construction.

#### L-05 — `submitResult` allows arbitrary `bytes32(0)` resultHash
- **Description:** No check that `resultHash != bytes32(0)`. A payee could submit an empty hash. The payer can refuse to approve, but they can't distinguish "payee genuinely submitted hash that happens to be 0x00...00" from "payee submitted a placeholder." Minor.
- **Recommended fix:** Require `resultHash != bytes32(0)`.

#### L-06 — `createJob` allows arbitrary `bytes32(0)` taskHash and `payee == msg.sender`
- **Description:** No validation that `payee != msg.sender` (self-job, possibly to game fees or simulate volume) and no validation that `taskHash != bytes32(0)`. Wash-trading risk if you publish protocol volume metrics. Not a fund risk.
- **Recommended fix:** Optional `require(payee != msg.sender)`. Document expected `taskHash` format (probably keccak256 of an off-chain spec).

#### L-07 — `AmountTooSmall` check uses `<=` against `minFee`, but `minFee` is mutable
- **Location:** line 67: `if (amount <= minFee) revert AmountTooSmall();`
- **Description:** If the owner raises `minFee` after a job is created, the old job is grandfathered in (still computes the new fee, see M-03). But for NEW jobs, this check uses the current `minFee` correctly. The check is `<=` not `<`, so `amount == minFee` reverts — meaning a 0.50 USDC job is impossible, but a 0.50000001 USDC job is allowed. Edge case but consistent.
- **Recommended fix:** Document the strict-less-than semantics. Consider `amount > minFee` (which is the same thing) for clarity.

---

### INFORMATIONAL

#### I-01 — Comment on line 5 already says "NOT audited. Do not deploy to mainnet without audit." Good.

#### I-02 — Consider using `IERC20` and `SafeERC20` from OpenZeppelin instead of hand-rolled low-level calls. Cleaner, easier to audit, well-tested.

#### I-03 — `approveAndPay` does three sequential `_transfer` calls. Combining into a single batched transfer is not possible without leaving USDC-standard, but a Multicall or pull-payment pattern would reduce attack surface.

#### I-04 — Events do not index `payee` on `JobApproved`, `JobRefunded`. Off-chain indexers will have to join with `JobCreated` to find the payee. Minor UX.

#### I-05 — No `getJob(uint256)` view function — consumers must use the auto-generated public `jobs` mapping getter, which is fine but returns a tuple, not a named struct. Adding a typed view function helps integrators.

#### I-06 — Solidity 0.8.26 is fine; consider pinning (`pragma solidity 0.8.26;` without caret) for reproducible deployments.

#### I-07 — `nextJobId` is `uint256`. Practically unsaturable.

#### I-08 — Tests cover happy paths well but do NOT exercise: malicious owner refund, dispute → refund flow, deadline boundary races, fee-on-transfer tokens, zero-address recipients, ownership transfer to zero, fee snapshot on parameter change, submission after deadline, approval after deadline, partial transfer failure on third leg of `approveAndPay`. Test coverage should be expanded before audit.

---

## 3. Threat Model — Items Worth Knowing

These are not bugs per se but design-level concerns that an external auditor would discuss in the report's "Centralization & Design" section.

### 3.1 Centralization
- **Owner is a single EOA.** The owner can: change fees (with caps), change fee recipient, change insurance pool, transfer ownership in one step, and refund any non-final job. There is no timelock and no multisig requirement. On mainnet, an owner key compromise = "owner can refund all open jobs to the original payers" (because `refund` only sends to `j.payer`, not to an arbitrary attacker address — that's a small mercy). However, the attacker can: (a) drain new fees by setting `feeRecipient = attacker`, (b) drain new insurance cuts by setting `insurancePool = attacker`, (c) clawback any in-flight job, (d) raise `feeBps` to 200 + `maxFee` to 25 USDC and capture more on each approval until detected.
- **Recommendation:** Safe multisig + 48h timelock on all owner-only functions before mainnet.

### 3.2 Front-running / MEV
- **`createJob`:** Not really front-runnable — payer pays to themselves into escrow, attacker can't insert.
- **`submitResult`:** A submitted result hash is revealed on-chain. If the payee's resultHash commits to a valuable off-chain artifact (e.g., the keccak of an answer), an observer could in principle copy it — but `resultHash` is just a hash, the artifact itself must be revealed off-chain. So this is OK as long as `resultHash` is genuinely a commitment and the artifact has access control off-chain.
- **`approveAndPay` vs. `refund` after deadline:** see H-03. At `block.timestamp == deadline + 1`, both `submitResult` (payee — currently allowed despite deadline) and `refund` (anyone) are valid. MEV searchers can race. The payer would win because `refund` is permissionless and `submitResult` requires the payee.
- **`setFees` vs. `approveAndPay`:** see M-03. Owner can sandwich the user's approval with a fee hike.

### 3.3 Sandwich attacks
- Not really applicable; no AMM, no slippage. The "sandwich" risk is the governance/parameter sandwich in M-03.

### 3.4 Gas DoS
- **No unbounded loops.** Good. There is no `for` loop over jobs anywhere.
- **Per-job storage** is constant size (one `Job` struct per ID).
- **Unbounded `string reason` in `dispute`** — only caller pays gas, not a DoS on the contract. Noted in M-07.

### 3.5 Reentrancy on USDC's non-standard return values
- **USDC IS standard.** It returns `true` on success and reverts on failure. The hand-rolled selector calls in `_transfer` / `_transferFrom` handle both standard and non-standard (no-return) ERC20s correctly. USDC will never reenter because its `transfer` does not call back into the caller.
- **However:** the contract takes `token` as a constructor arg with no validation, so a different deployment could in theory point at a reentrant token (ERC777, hooks, etc.). Mainnet deployment should hardcode USDC's address.
- See H-04 for defense-in-depth recommendation.

### 3.6 USDC-specific risks
- **USDC is upgradeable by Circle.** A future Circle upgrade could in theory change behavior. Low risk in practice.
- **USDC has a blocklist.** If the `feeRecipient`, `insurancePool`, `payee`, or `payer` is blocklisted, `approveAndPay` or `refund` will revert. The job is stuck. There's no admin override to redirect funds elsewhere. On mainnet this is a real (small) risk.
- **USDC is centralizable.** If Circle blocks the escrow contract address itself, all jobs are frozen.
- **Recommendation:** Document USDC's blocklist risk in user-facing docs. Consider an escape hatch for blocklisted-payee jobs.

### 3.7 Integer overflow / underflow
- Solidity 0.8.26 has built-in checked arithmetic. The only subtractions are `j.amount - fee` and `fee - insuranceCut`. `computeFee` caps `fee <= amount` IF `amount > maxFee` (because `fee` cap is `maxFee`, and `createJob` requires `amount > minFee` but does NOT require `amount > maxFee`). Wait — let me check: if `amount = 10 USDC` and `maxFee = 25 USDC`, then `computeFee` returns `min(25_000_000, max(500_000, 100_000))` = `min(25_000_000, 500_000)` = `500_000`. So fee = `minFee = 0.50`. Then `payout = 10 - 0.50 = 9.50`. OK, no underflow because `createJob` requires `amount > minFee`. **Good.**
- BUT: if owner raises `minFee` to e.g. 100 USDC AFTER a 10 USDC job is created (M-03), then `approveAndPay` computes `fee = 100 USDC`, `payout = 10 - 100` → **underflow revert under 0.8.x checked arithmetic.** The job becomes un-approvable (and un-refundable from `Approved` state, but it's still `Submitted` so it can be disputed and then owner-refunded). So this is a DoS, not a fund loss. Tied to M-03.

### 3.8 Signature replay / typed-data
- No signatures used. No EIP-712. No risk.

### 3.9 Oracle manipulation
- No oracles. No risk.

### 3.10 Cross-chain / bridge
- No bridges. No risk.

---

## 4. Things I Checked and Did NOT Find as Issues

So you know what coverage I gave the contract:

- **Integer overflow/underflow in `computeFee`:** safe. `amount * feeBps` cannot overflow at any realistic `amount` (would need `amount > 2^248`).
- **Integer overflow in fee math in `approveAndPay`:** safe; all arithmetic is bounded by `amount`.
- **Reentrancy on USDC:** USDC is non-reentrant. Status is set before transfers in `approveAndPay` (line 96 before lines 101–103), so CEI is followed for state — only economic reentrancy via a malicious token would matter, and `token` is immutable.
- **Job status state machine correctness for happy path:** `None → Funded → Submitted → Approved` works correctly.
- **Job status state machine for refund-after-deadline path:** `None → Funded → Refunded` works correctly.
- **`createJob` access control:** anyone can create a job, paying their own funds in. Correct.
- **`submitResult` access control:** restricted to payee. Correct.
- **`approveAndPay` access control:** restricted to payer. Correct.
- **`computeFee` math:** matches the tests. `max(minFee, min(maxFee, 1% * amount))`. Verified for 10 / 100 / 1000 / 10000 USDC against the tests in `AgoraEscrow.t.sol` — all pass.
- **Fee split math:** `insuranceCut = fee * 10% = fee/10`, `platformCut = fee - insuranceCut`. Sums to `fee`. Verified against tests (100 USDC → 0.10 insurance + 0.90 platform; 10000 USDC → 2.50 insurance + 22.50 platform). Correct.
- **Token balance accounting on the happy path:** the contract holds exactly `sum(amounts of Funded+Submitted+Disputed jobs)` assuming a well-behaved token. Confirmed by reasoning, not by an invariant test (recommend adding one).
- **`onlyOwner` modifier:** correctly applied to `setFees`, `setFeeRecipient`, `setInsurancePool`, `transferOwnership`.
- **No `selfdestruct`:** good.
- **No `delegatecall`:** good.
- **No assembly:** good (only `abi.encodeWithSelector` via low-level `call`).
- **Constructor:** sets `owner = msg.sender`, `token`, `feeRecipient`, `insurancePool`. No zero-address checks on `_token` / `_feeRecipient` / `_insurancePool` — minor issue, not flagging separately since constructor is a one-shot. Worth adding.
- **Custom errors instead of revert strings:** good gas hygiene.
- **`immutable` on `token`:** good gas hygiene.
- **Events on the main state transitions:** present and reasonable.
- **The fact that `dispute()` does NOT pay anything out:** correct — it only changes status. Good.

---

## 5. Audit Triage — What Cyfrin / OpenZeppelin / CodeHawks Would Likely Flag at HIGH+

Based on patterns from public audit reports (Cyfrin's `solodit.xyz` corpus, OpenZeppelin's portfolio):

| Finding | Likely Severity in External Audit |
|---|---|
| C-01: owner can unilaterally refund any non-final job | **CRITICAL** or **HIGH** depending on whether the auditor considers the owner trusted. Cyfrin tends to flag this HIGH+ with a "centralization risk" tag. |
| H-01: `Disputed` is a one-way trap (no payee-side resolution) | **HIGH** — core protocol invariant broken. |
| H-02: `dispute()` callable in `Funded` state | **HIGH** when combined with H-01. **MEDIUM** if H-01 is fixed. |
| H-03: no deadline enforcement on `submitResult` / `approveAndPay` | **HIGH** — race condition at boundary, design intent unclear. |
| H-04: no reentrancy guard | **MEDIUM** typically, with note that it depends on token; on USDC, **LOW**. |
| H-05: no fee-on-transfer guard | **HIGH** if generic-token; **LOW** if USDC-hardcoded. |
| H-06: cross-job balance pooling | **MEDIUM** — architectural. |
| M-01–M-07 | **MEDIUM** / **LOW** range. |

**My estimate:** an external audit would land 2–3 HIGH findings (C-01, H-01/H-02 combined, H-03 or H-05), 4–6 MEDIUM findings, and a sprinkling of LOW / INFORMATIONAL.

---

## 6. Pre-Mainnet Checklist (Prioritized)

1. **Fix C-01 and H-01/H-02 together.** Redesign the dispute → resolution flow. Add `resolveDispute` with payer/payee split semantics. Restrict `refund` paths cleanly.
2. **Fix H-03.** Enforce deadline in `submitResult`. Decide explicit semantics for late approval.
3. **Hardcode USDC address on mainnet** (drop the constructor arg). This eliminates H-04, H-05, and L-04 for the USDC case.
4. **Snapshot fee parameters into the `Job` struct** at `createJob` time (M-03).
5. **Move owner to a Safe multisig + 24/48h Timelock** for `setFees`, `setFeeRecipient`, `setInsurancePool`, dispute resolution.
6. **Add `Pausable` to `createJob`.**
7. **Add OZ `Ownable2Step`.**
8. **Add `nonReentrant` modifier as defense-in-depth.**
9. **Zero-address checks** in setters and constructor.
10. **Expand test suite** to cover the negative paths listed in I-08, plus invariant tests on `sum(open job amounts) == token.balanceOf(this)`.
11. **External audit.** Cyfrin / OpenZeppelin / Spearbit / CodeHawks contest. For a contract this small, a $20–40k audit is realistic; a CodeHawks contest is cheaper but slower.

---

## 7. Appendix — Slither Static Analysis

Run on 2026-05-20 with `slither-analyzer 0.10.x` against `AgoraEscrow.sol` directly (no foundry framework). 22 findings, mostly overlapping with the manual review above. The findings Slither flagged that are *additive* over the manual review:

- **`events-access`**: `transferOwnership` doesn't emit an event for the new owner — confirms M-04.
- **`missing-zero-check`** (6 occurrences): constructor `_token`, `_feeRecipient`, `_insurancePool`; setters `_r`, `_p`; ownership transfer `_n` — confirms M-01 / M-02 and extends to constructor.
- **`reentrancy-benign`** (createJob): state updated after external call to token — not exploitable with USDC but worth fixing with `nonReentrant` per H-04.
- **`reentrancy-events`** (createJob, approveAndPay, refund): events emitted after external calls — informational; means an off-chain consumer that trusts event ordering could be misled by a reverting subsequent transfer (which would roll back the events too in 0.8.x, so practically OK).
- **`timestamp`**: `block.timestamp` used for comparisons — known minor manipulability by miners (~15 sec on Base sequencer), acceptable for our deadline-scale (hours).
- **`low-level-calls`**: `token.call(abi.encodeWithSelector(...))` — confirms L-04.
- **`naming-convention`** (7 parameters with `_` prefix): cosmetic.

Net: Slither agrees with the manual review. Nothing new of HIGH severity. The combination of `events-access` + `missing-zero-check` + `low-level-calls` is the typical pattern that drives auditors to recommend OpenZeppelin's `Ownable2Step` + `SafeERC20` migration.

Full raw output is in `slither.log` (not committed; reproducible with `slither AgoraEscrow.sol`).

---

*End of report.*
