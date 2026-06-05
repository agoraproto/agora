# RUNBOOK — Deploy TimelockController to Base Sepolia

**Sprint 45 / Option B**. One-time deploy. Idempotent? No — running this
twice deploys two Timelocks.

## Pre-flight

You need:
- `PRIVATE_KEY` env var with the deployer (gas-payer; gets no Timelock role)
- `SAFE_ADDRESS` env var = `0x8Ec63Fe30DAb84308B5009b8D91d9E4dEB5a61FC` (the V2 owner Safe)
- Sepolia ETH on the deployer (~0.005 ETH covers it comfortably)
- `BASESCAN_API_KEY` env var for `--verify`

## Deploy + verify

```powershell
# From your local workstation, run on the agora-1 server via SSH:
# (deployer key + Basescan key already live in /opt/agora/experiments/swarm/.env)

ssh root@188.245.39.250 bash <<'SH'
set -euo pipefail
cd /opt/agora/contracts
source /opt/agora/experiments/swarm/.env  # PRIVATE_KEY=DEPLOYER_KEY, BASESCAN_API_KEY
export SAFE_ADDRESS=0x8Ec63Fe30DAb84308B5009b8D91d9E4dEB5a61FC

forge script script/DeployTimelock.s.sol:DeployTimelock \
  --rpc-url base_sepolia \
  --broadcast --verify \
  --etherscan-api-key "$BASESCAN_API_KEY" \
  -vv
SH
```

## What the deploy emits

Look for:

```
TimelockController deployed at: 0x<TIMELOCK_ADDR>

Roles assigned:
  PROPOSER_ROLE   -> Safe (0x8Ec6...)
  CANCELLER_ROLE  -> Safe
  EXECUTOR_ROLE   -> Safe
  DEFAULT_ADMIN_ROLE -> Timelock itself
```

## Post-deploy verification

Sanity-check the role + delay configuration before going anywhere near
`transferOwnership`. The Timelock is permanent — once V2 ownership is
on the Timelock, only the Timelock can move it.

```bash
CAST=/root/.foundry/bin/cast
RPC=https://sepolia.base.org
TL=0x<TIMELOCK_ADDR>          # from deploy output
SAFE=0x8Ec63Fe30DAb84308B5009b8D91d9E4dEB5a61FC

# 1) minDelay = 86400 ?
$CAST call $TL "getMinDelay()(uint256)" --rpc-url $RPC
# Expect: 86400

# 2) Safe has PROPOSER_ROLE ?
PROPOSER_ROLE=$($CAST call $TL "PROPOSER_ROLE()(bytes32)" --rpc-url $RPC)
$CAST call $TL "hasRole(bytes32,address)(bool)" $PROPOSER_ROLE $SAFE --rpc-url $RPC
# Expect: true

# 3) Safe has EXECUTOR_ROLE ?
EXECUTOR_ROLE=$($CAST call $TL "EXECUTOR_ROLE()(bytes32)" --rpc-url $RPC)
$CAST call $TL "hasRole(bytes32,address)(bool)" $EXECUTOR_ROLE $SAFE --rpc-url $RPC
# Expect: true

# 4) Safe has CANCELLER_ROLE ?
CANCELLER_ROLE=$($CAST call $TL "CANCELLER_ROLE()(bytes32)" --rpc-url $RPC)
$CAST call $TL "hasRole(bytes32,address)(bool)" $CANCELLER_ROLE $SAFE --rpc-url $RPC
# Expect: true

# 5) Nobody external has DEFAULT_ADMIN_ROLE ?
ADMIN_ROLE=$($CAST call $TL "DEFAULT_ADMIN_ROLE()(bytes32)" --rpc-url $RPC)
$CAST call $TL "hasRole(bytes32,address)(bool)" $ADMIN_ROLE $SAFE --rpc-url $RPC
# Expect: false
$CAST call $TL "hasRole(bytes32,address)(bool)" $ADMIN_ROLE $TL --rpc-url $RPC
# Expect: true   (self-administered)
```

Only proceed to `RUNBOOK_OWNERSHIP_FLIP.md` if **all five** match.

## What to update after deploy

1. `apps/website/llms.txt` — add the Timelock address.
2. `apps/website/.well-known/ai-services.json` — add the Timelock address.
3. `contracts/SECURITY_REVIEW_V2.md` — record the deployed Timelock address.
4. `apps/backend/src/agora_api/config.py` — no change needed yet
   (escrow_contract_address still points to V2; backend has no need to
   know about the Timelock).
