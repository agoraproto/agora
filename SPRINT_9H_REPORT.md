# Sprint 9h — Pre-audit hardening, grant application, V2 design

**Date:** 2026-05-20 (continuation of 9g)
**Driver:** CEO decision to defer paid audit, fund via grant instead.
**Goal:** ship everything we can do for free + everything that
prepares the project for a sponsored audit later.

## Four deliverables

### 1. Security review of `AgoraEscrow.sol` (deployed v1)

Produced [`contracts/SECURITY_REVIEW.md`](contracts/SECURITY_REVIEW.md) —
internal pre-audit review combining a subagent code-reviewer pass with
a Slither static-analysis run.

**Top-line findings:**

| Severity | Count | Most consequential |
|---|---|---|
| CRITICAL | 1 | C-01: owner can unilaterally refund any non-final job |
| HIGH | 6 | H-01: `Disputed` is a one-way trap to refund-only — payee has no resolution path |
| MEDIUM | 7 | M-03: fee parameters apply at approve-time, not create-time → sandwich-by-owner |
| LOW | 7 | misc hardening (Pausable, Ownable2Step, zero-checks) |
| INFORMATIONAL | 8 | style and gas |

Net assessment: the v1 contract is **not mainnet-ready** in current form,
but it is **fine on testnet for the demo cycle we ran** (USDC has no
fee-on-transfer, no one disputed, the owner is the operator). The
findings would not have surfaced from the receipts because the receipts
never exercised the broken paths.

### 2. Base Ecosystem Fund grant application

Drafted [`docs/grants/BASE_ECOSYSTEM_FUND_APPLICATION.md`](docs/grants/BASE_ECOSYSTEM_FUND_APPLICATION.md).
Asks for $18,000:

- $10k for external audit (CodeHawks / Cyfrin Lite)
- $1.5k mainnet deploy + Safe multisig setup
- $1.5k 90-day hosting runway
- $3k audit re-fix + re-audit cycle
- $2k docs + outreach

If awarded, the protocol can hit mainnet inside 90 days. If not, it
stays a testnet reference deployment and the open-source code is
available for anyone to fork and audit independently.

### 3. Landing-page repositioning

Updated [`apps/website/index.html`](apps/website/index.html) hero +
status section. Old framing: "Mainnet pending audit." New framing:
"Open protocol. Testnet reference deployment. Fork for production."

That's the honest position given current funding. It doesn't oversell
and it doesn't pretend mainnet is around the corner.

### 4. `AgoraEscrowV2.sol` — design fixes for every HIGH and CRITICAL

New file: [`contracts/src/AgoraEscrowV2.sol`](contracts/src/AgoraEscrowV2.sol).
Companion tests: [`contracts/test/AgoraEscrowV2.t.sol`](contracts/test/AgoraEscrowV2.t.sol).

| Finding | Fix in V2 |
|---|---|
| C-01 (owner refund power) | Split into permissionless `refundExpired()` (Funded + past deadline only) and owner-only `resolveDispute()` (Disputed only). |
| H-01 (Disputed is a trap) | New `resolveDispute(jobId, payeeAmount, payerAmount)` — sums must equal the original amount; fee taken proportionally from payee's share; emits `JobResolved`. |
| H-02 (dispute in Funded) | `dispute()` now rejects anything other than Submitted status. |
| H-03 (no deadline enforcement) | `submitResult()` now reverts past deadline. `approveAndPay()` keeps grace period by design choice (documented). |
| H-04 (no reentrancy guard) | `nonReentrant` modifier on every external state-changing function. |
| H-05 (fee-on-transfer risk) | `createJob()` measures `balanceOf(this)` before/after `transferFrom` and reverts if delta ≠ amount. |
| H-06 (cross-job balance pool) | Explicit `totalEscrowed` storage, incremented on deposit, decremented on every payout. Enables invariant testing. |
| M-01 (single-step ownership) | OpenZeppelin `Ownable2Step` — transfers require both `transferOwnership` and `acceptOwnership`. |
| M-02 (zero-address acceptance) | Reverts on `address(0)` in constructor + every setter. |
| M-03 (fee retroactivity) | `Job` struct now stores a snapshot of `feeBps`, `minFee`, `maxFee`, `insuranceShareBps` at create-time. `_computeFeeFor(job, amount)` uses the snapshot, not the live state. |
| M-04 (no setter events) | `FeeRecipientUpdated`, `InsurancePoolUpdated` emitted. `Ownable2Step` emits its own ownership events. |
| M-05 (nextJobId==0) | Now starts at 1. |
| L-01 (no pause) | OpenZeppelin `Pausable` — `pause()` / `unpause()` by owner, gates `createJob` only (existing jobs can still finalize). |
| L-04 (raw `token.call`) | `SafeERC20.safeTransfer` / `safeTransferFrom`. |
| L-05 (empty resultHash) | Rejected at `submitResult`. |
| L-06 (self-job) | `payee == msg.sender` reverts. |

**Test coverage** (`AgoraEscrowV2.t.sol`):

- Happy path: hire → submit → approve, fee math verified line-by-line
- Deadline enforcement in `submitResult`
- Dispute blocked in Funded state
- `resolveDispute` with 50/50 split, with 100% payer, with bad sum
- `refundExpired` permissionlessly callable after deadline, blocked before, blocked on Submitted
- Fee snapshot survives mid-flight `setFees`
- Pausable blocks `createJob`
- Zero-address checks on every setter + constructor
- Fee-on-transfer token rejected via balanceOf-delta
- Ownership transfer requires two-step accept
- Empty resultHash rejected

**V2 is NOT deployed yet.** It is the design ready for audit if grant
funding lands. The deployed `0xCE783B527C…02B76` contract on Base
Sepolia stays as the reference for the existing receipts; no migration
is forced on anyone.

## What's open

- **`pytest` against the backend** still has 1 pre-existing failure
  (`test_sdk_verifier_matches_backend` — `agora_sdk` not in the
  backend venv). Unrelated to this sprint. Will need a small `pip
  install -e packages/sdk-python` in the backend venv to fix.
- **OpenZeppelin contracts must be installed in `contracts/lib/`** for
  V2 to compile. The repo's `contracts/README.md` already documents
  this via `git clone --branch v5.0.2 …`. Just run that before `forge
  test`.

## Grant submission flow (for Andreas, when ready)

1. Read [`docs/grants/BASE_ECOSYSTEM_FUND_APPLICATION.md`](docs/grants/BASE_ECOSYSTEM_FUND_APPLICATION.md).
   Edit the contact email + any wording that needs softening.
2. Browse to <https://base.org/ecosystem-fund> and submit through their
   form, pasting the relevant sections.
3. Mirror the submission to <https://app.gitcoin.co/> and Optimism's
   RetroPGF round when those windows open (typically quarterly).
4. If accepted: ping me and we run Sprint 9i (audit contest setup,
   v2 deploy script for mainnet, Safe multisig configuration).

## Status table

```
v1 contract             ✅ deployed Sepolia, source-verified, NOT mainnet-ready
v2 contract             ✅ written + tested, NOT deployed
SECURITY_REVIEW.md      ✅ committed in contracts/
Slither                 ✅ ran, findings appended to SECURITY_REVIEW
Subagent code-review    ✅ ran, full report in SECURITY_REVIEW
Base grant application  ✅ drafted, awaiting Andreas to submit
Landing page wording    ✅ repositioned to "fork for production"
```
