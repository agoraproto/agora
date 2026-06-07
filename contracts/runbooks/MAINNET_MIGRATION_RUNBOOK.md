# Mainnet Migration Runbook — V2 (Sepolia) → V2.1 (Sepolia) → V2.1 (Base Mainnet)

**Sprint 48, 2026-06-06.** Living document. Updated as each phase lands.

This runbook describes the full path from "V2 lives on Sepolia" today to
"V2.1 lives on Base Mainnet, all agent traffic routes there, V2 is legacy."
It is written so Andreas (operator) can execute it end-to-end without
guessing what comes next.

## Hard prerequisites

Before phase A starts:

- ☑ Sprint 45: Timelock Code-Side landed (commit `d77c288`)
- ☑ Sprint 46: ADR adopted (commit `6b80e18`)
- ☑ Sprint 47: V2.1 contract spike landed (commit `6b80e18`, tag `sprint-47-v21-spike`)
- ☐ Sprint 45 on-chain: Timelock deployed on Sepolia + ownership flipped
  (gated on Andreas executing `experiments/timelock/RUNBOOK_DEPLOY.md` +
  `RUNBOOK_OWNERSHIP_FLIP.md`)
- ☐ External V2.1 audit feedback ingested (gated on external reviewers)

Until those two unchecked items are done, this runbook stays in
"prepared" state.

---

## Phase A — V2.1 on Sepolia (the dry run)

Goal: ship V2.1 to the same Sepolia environment V2 already lives in, so
backend dispatch, swarm agents, and admin tooling can be exercised against
V2.1 before any Mainnet bits move.

### A.1 — Deploy V2.1 to Sepolia

```bash
ssh root@188.245.39.250 bash <<'SH'
set -euo pipefail
cd /opt/agora/contracts
source /opt/agora/experiments/swarm/.env
export USDC_ADDRESS=0x036CbD53842c5426634e7929541eC2318f3dCF7e
export USDC_DECIMALS=6
export FEE_RECIPIENT=<andreas-wallet>
export INSURANCE_POOL=<andreas-wallet>   # same as V2 today

forge script script/DeployV21.s.sol:DeployV21 \
  --rpc-url base_sepolia \
  --broadcast --verify \
  --etherscan-api-key "$BASESCAN_API_KEY"
SH
```

Note: `script/DeployV21.s.sol` does NOT exist yet. Copy `DeployV2.s.sol` →
`DeployV21.s.sol` and rename the import. Trivial commit.

Record the deployed address as `V21_SEPOLIA`.

### A.2 — Set V2.1 roles (pauser + disputeResolver = Safe)

Two `safe-admin-op.sh` calls with `TARGET=$V21_SEPOLIA`:

```bash
CALLDATA1=$($CAST calldata "setPauser(address)" $SAFE)
CALLDATA2=$($CAST calldata "setDisputeResolver(address)" $SAFE)
```

After both broadcast, verify:
```bash
$CAST call $V21_SEPOLIA "pauser()(address)" --rpc-url $RPC
# Expect: 0x8Ec6... (Safe)
$CAST call $V21_SEPOLIA "disputeResolver()(address)" --rpc-url $RPC
# Expect: 0x8Ec6... (Safe)
```

### A.3 — Transfer V2.1 ownership to Timelock

Same two-phase pattern as in `experiments/timelock/RUNBOOK_OWNERSHIP_FLIP.md`,
but with V2.1 as the target:

1. Safe.execTransaction → `V21_SEPOLIA.transferOwnership(timelock)`
2. Safe.execTransaction → `Timelock.schedule(V21_SEPOLIA, 0, V21.acceptOwnership(), ...)`
3. Wait 24h
4. Anyone with EXECUTOR_ROLE (Safe) → `Timelock.execute(...)`

Verify: `V21_SEPOLIA.owner() == timelock`, `V21_SEPOLIA.pauser() == Safe`,
`V21_SEPOLIA.disputeResolver() == Safe`.

### A.4 — Backend dispatch: teach `escrow.py` about V2.1

Single backend change. `apps/backend/src/agora_api/chain/escrow.py` already
has V1/V2 dispatch (Sprint 36c). Add V2.1:

```python
# config.py: new field
escrow_abi_version: Literal["v1", "v2", "v2.1"] = "v2"

# escrow.py constructor: add v2.1 ABI definition (superset of V2)
ESCROW_ABI_V21 = ESCROW_ABI_V2 + [
    {"name": "payeeForceApprove", "inputs": [{"name": "jobId", "type": "uint256"}], ...},
    {"name": "setPauser", "inputs": [{"name": "p", "type": "address"}], ...},
    {"name": "setDisputeResolver", "inputs": [{"name": "r", "type": "address"}], ...},
    # plus new events: PauserUpdated, DisputeResolverUpdated, JobApprovedByPayeeForce
]
```

`apps/backend/src/agora_api/routes/x402.py` — the V2 path works as-is for
all V2.1 calls because the V2 selectors are still valid on V2.1. The new
`/v1/x402/payee-force-approve` endpoint can wait for a follow-up sprint
(or be a manual cast call until then).

### A.5 — Flip backend to V21_SEPOLIA

Two-line config change in `/opt/agora/apps/backend/.env`:
```
ESCROW_CONTRACT_ADDRESS=<V21_SEPOLIA>
ESCROW_ABI_VERSION=v2.1
```

Auto-pull restarts the API. V1 + V2 jobs still resolve correctly (escrow.py
keeps the legacy ABIs); new jobs route to V2.1.

### A.6 — Soak test (≥ 7 days)

Let the 20-agent swarm run V2.1 traffic for at least a week. What to watch:

- Daily admin dashboard glance: any errors, any drift, any unexpected
  events
- `payeeForceApprove` triggered by any swarm provider (artificial test):
  one V2.1 job, payee submits then payer "forgets," after 7d payee runs
  the force-approve via cast. Expect: payee gets funds, no owner involved.
- `refundExpired` triggered by payer on Submitted: similar artificial test,
  expect refund after 3d.
- Pause smoke: Safe pauses V2.1 directly (no Timelock proposal needed),
  V2.1 reverts everything, Safe unpauses via Timelock schedule + 24h +
  execute. Use this to confirm Option A-style direct pause is what we
  wanted out of Option B.

If anything misbehaves: rollback to V2 by re-flipping the backend env
back to V2_SEPOLIA. V2 is still owned by the Safe directly (not the
Timelock), so it's instant.

---

## Phase B — External audit ingestion

This phase is BLOCKED on external reviewers. Outline only.

Whoever audits V2.1 lands findings in GitHub Issues. Each issue gets:
- A severity label (CRITICAL / HIGH / MEDIUM / LOW / INFO)
- A "blocks mainnet" or "blocks mainnet-1.0" tag

CRITICAL + HIGH must be fixed and re-audited before Phase C. MEDIUM is
case-by-case. LOW + INFO can ship as documented limitations.

Each fix lands as a separate V2.1.x patch commit. We do NOT rev to V2.2
unless the audit specifically requires breaking changes.

---

## Phase C — Mainnet deploy of V2.1

Goal: deploy V2.1 to Base Mainnet at the audited revision.

### C.1 — Pre-flight checklist

- ☐ Mainnet deployer wallet funded with ETH (~0.05 ETH covers V2.1 + Timelock)
- ☐ Mainnet Safe deployed (separate from Sepolia Safe; new addresses, new
  cosigner keys -- testnet keys are burned by definition)
- ☐ Mainnet USDC address verified: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- ☐ All Phase B findings closed at the audited revision
- ☐ Snapshot of repo at the audited revision tagged (e.g. `mainnet-v21-deploy`)
- ☐ Andreas reviewed the diff vs. Sepolia-deployed V2.1 byte-for-byte

### C.2 — Deploy order

1. Deploy Mainnet TimelockController (same `DeployTimelock.s.sol`, but
   `SAFE_ADDRESS` = Mainnet Safe).
2. Deploy V2.1 to Mainnet (`DeployV21.s.sol` with USDC = Mainnet USDC).
3. Verify both on Basescan.
4. Mainnet Safe sets V2.1 roles (`setPauser(Safe)`, `setDisputeResolver(Safe)`).
5. Mainnet Safe transferOwnership(timelock).
6. Mainnet Safe schedules `V21.acceptOwnership()` via Timelock.
7. **Wait 24h.**
8. Mainnet Safe executes the acceptOwnership.
9. Verify final state: V2.1 owner = Timelock, pauser = Safe, resolver = Safe.

### C.3 — Backend config for Mainnet

`apps/backend/.env.production`:
```
CHAIN_ID=8453
RPC_URL=https://mainnet.base.org
USDC_CONTRACT_ADDRESS=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
ESCROW_CONTRACT_ADDRESS=<V21_MAINNET>
ESCROW_ABI_VERSION=v2.1
```

The auto-pull pipeline picks this up and restarts the API. Mainnet smoke
test: one `cast` call, one tiny job through x402, observe webhook, observe
USDC flow.

### C.4 — Initial Mainnet pause queue

Same as Sepolia: queue an emergency pause proposal at deploy + 1h, then
roll it every 23h. `RUNBOOK_PERMANENT_PAUSE_QUEUE.md` applies verbatim.

For Mainnet, automate this. The 24h delay window is real risk.

---

## Phase D — Frontend + website update

- `apps/website/llms.txt` -- update Mainnet addresses
- `apps/website/.well-known/ai-services.json` -- update Mainnet addresses
- `apps/website/live.html` -- point at Mainnet RPC, label Sepolia view as
  "Testnet" if we keep showing it
- `apps/website/index.html` -- swap any "Sepolia" mentions to "Mainnet"

Auto-pull handles deployment.

---

## Phase E — V2 retirement (eventual)

V2 stays live on Sepolia indefinitely as audit-trail artifact. Active
agent traffic moves off V2 in Phase A (when backend flips to V2.1). V1
already has the `experiments/v1-cleanup/cleanup.sh` script for the
~10 USDC stuck (Sprint 42).

When the last V2 job reaches terminal state (Approved / Refunded /
Resolved), V2's `totalEscrowed` is 0 and the contract can be left as-is.
No `selfdestruct`, no migration. It stays as a contract address that
no longer receives traffic.

---

## Rollback decisions per phase

| If something breaks in... | Roll back to | How |
|---|---|---|
| Phase A (Sepolia V2.1 traffic) | V2 Sepolia | Backend `.env` flip; restart |
| Phase A (V2.1 ownership flip) | V2.1 self-owned | If pre-flip: cancel via Timelock CANCELLER role; if post-flip: schedule `transferOwnership(Safe)` back via Timelock, 24h wait |
| Phase B | n/a | External findings drive fixes; no rollback |
| Phase C (Mainnet deploy) | "Mainnet not live" | Don't flip backend `.env.production`; Mainnet V2.1 stays unused |
| Phase C (after backend flip) | V2 Sepolia (= testnet only) | Backend `.env.production` rollback; Mainnet V2.1 stays deployed but unused |
| Phase D | previous llms.txt | git revert + auto-pull |

---

## Sequencing summary

```
NOW: V2 on Sepolia (Safe-owned, no Timelock yet)
  |
  +--> Phase A.1-A.6 -- V2.1 on Sepolia (Timelock-owned, ~7 days)
  |        \-- requires Sprint 45 on-chain done first
  |
  +--> Phase B -- external audit (timeline external)
  |
  +--> Phase C.1-C.4 -- V2.1 on Mainnet
  |
  +--> Phase D -- frontend update
  |
  +--> Phase E (asymptotic) -- V2 retired
```

Total realistic timeline assuming external audit feedback is fast:
- Phase A: 1-2 weeks (deploy + 7-day soak)
- Phase B: external, plan for 4 weeks
- Phase C: 2-3 days (deploy + 24h Timelock-wait + smoke)
- Phase D: 1 hour

Without external audit: do not proceed past Phase A. Mainnet without
external review is not a story we can tell.
