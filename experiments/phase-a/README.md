# Phase A — V2.1 rollout on Sepolia

Click-ready scripts for the Phase-A path of
`contracts/runbooks/MAINNET_MIGRATION_RUNBOOK.md`.

These scripts are NOT to be run until either:
  * the external V2.1 audit has come back without CRITICAL/HIGH findings,
    AND the operator has decided to proceed; or
  * the operator explicitly wants to test the deploy on Sepolia before
    the audit (acceptable for testnet practice).

## Scripts

### `deploy-v21-sepolia.sh` (Phase A.1)

Deploys `AgoraEscrowV21` to Base Sepolia.

```powershell
Get-Content C:\Users\WAVO\Desktop\Projekte\agor\experiments\phase-a\deploy-v21-sepolia.sh -Raw | ssh root@188.245.39.250 bash
```

Pre-flight checks:
- Repo on `main`, submodules initialised
- Deployer wallet has ≥ 0.0004 ETH
- V2.1 source files present at expected paths
- V2.1 + V2.1+Timelock Foundry tests pass at this revision

If all pre-flight checks pass, runs `forge script DeployV21.s.sol:DeployV21
--rpc-url base_sepolia --broadcast [--verify]`. Constructor args are read
from env: `USDC_ADDRESS`, `USDC_DECIMALS`, `FEE_RECIPIENT`, `INSURANCE_POOL`.
Defaults wired to Sepolia USDC + the Sprint-37 wallets.

Post-deploy: paste the `AgoraEscrowV21 deployed at: 0x...` line back to
the operator chat so the Phase A.2/A.3 scripts can be assembled with the
correct V2.1 address.

### `setup-v21-roles.sh` (Phase A.2)

[To be written once Phase A.1 has run and a V2.1 address exists.]

Safe-admin-op sequence: `V21.setPauser(Safe)` then `V21.setDisputeResolver(Safe)`.
Same DRY_RUN=1 / DRY_RUN=0 pattern as the Sprint-45 Safe-admin scripts.

### `flip-v21-ownership.sh` (Phase A.3)

[To be written once Phase A.2 has run.]

Three-step ownership flip (mirrors Sprint 45 phases 1, 2a, 2b but for V2.1):
1. `V21.transferOwnership(Timelock)` via Safe-admin-op
2. `Timelock.schedule(V21.acceptOwnership(), delay=86400)` via Safe-admin-op
3. Wait 24 h
4. `Timelock.execute(V21.acceptOwnership())` via Safe-admin-op

After flip, V2.1 is fully Timelock-owned with Safe as
proposer + canceller + executor of the Timelock.

### Phase A.4 — Backend `.env` flip (manual)

After the V2.1 ownership flip lands, edit `/opt/agora/apps/backend/.env`:

```
ESCROW_CONTRACT_ADDRESS=<V21_SEPOLIA_ADDR>
ESCROW_ABI_VERSION=v2.1
```

The auto-pull pipeline picks this up and restarts the API. Existing V1
+ V2 jobs continue to resolve correctly (escrow.py keeps the legacy ABIs
loaded for read-only ops); new jobs route to V2.1.

### Phase A.5 — Soak test (≥ 7 days)

Watch the 20-agent swarm against V2.1. What to look for:
- Daily admin dashboard glance
- One artificial `payeeForceApprove` test (deadline + 7d + 1s)
- One artificial `refundExpired` on Submitted test (deadline + 3d + 1s)
- One pause/unpause smoke: Safe pauses directly (no Timelock proposal),
  then Safe schedules + 24h + executes unpause via Timelock

## Rollback

If any phase blows up, V2 is still live and operational. The backend
`.env` flip in Phase A.4 is the only step that switches user traffic
to V2.1; reverting that one env-line takes traffic back to V2.

Phase A.3 (ownership flip) is the only on-chain action that's hard to
reverse without going through the Timelock again, but V2.1 is brand
new and has no escrow positions, so a re-transferOwnership scheduled
through the Timelock is purely operational, not a fund-safety risk.
