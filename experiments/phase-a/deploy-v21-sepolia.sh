#!/usr/bin/env bash
# Sprint 53 / Phase A.1 of MAINNET_MIGRATION_RUNBOOK.md:
#   Deploy AgoraEscrowV21 to Base Sepolia.
#
# This is the click-ready version of the deploy step. It mirrors the
# Sprint-45 timelock-deploy pattern: pre-flight checks, forge script,
# verify if BASESCAN_API_KEY is available, no state-mutation before
# --broadcast.
#
# Run from PowerShell:
#   Get-Content C:\Users\WAVO\Desktop\Projekte\agor\sprint53-deploy-v21-sepolia.sh -Raw | ssh root@188.245.39.250 bash
#
# What lands on-chain when --broadcast fires:
#   * New AgoraEscrowV21 contract at a fresh address
#   * Constructor sets the deployer (= PRIVATE_KEY holder) as Ownable2Step owner
#   * pauser and disputeResolver are address(0) -- owner sets them in
#     Phase A.2 (separate script)
#
# AFTER this script succeeds, the natural next steps are:
#   Phase A.2: sprint53b-setup-v21-roles.sh
#     - Safe-admin-op sequence: V21.setPauser(Safe), V21.setDisputeResolver(Safe)
#     - Run with DRY_RUN=1 first, then DRY_RUN=0
#   Phase A.3: sprint53c-flip-v21-ownership.sh
#     - V21.transferOwnership(Timelock)
#     - Timelock.schedule(V21.acceptOwnership(), delay=86400)
#     - Wait 24h
#     - Timelock.execute(V21.acceptOwnership())
#   Phase A.4: Backend .env flip
#     - ESCROW_CONTRACT_ADDRESS=<V21_ADDR>
#     - ESCROW_ABI_VERSION=v2.1
#
# All phase-A scripts will be added as separate sprint53b/c files when
# Phase A.1 has run successfully on Sepolia.

set -euo pipefail

# V2.1 constructor args (same as V2's: USDC token + fee + insurance wallets)
USDC_ADDRESS=0x036CbD53842c5426634e7929541eC2318f3dCF7e
USDC_DECIMALS=6
# Fee recipient + insurance pool: same as V2 was deployed with.
# CHANGE THESE if Andreas wants a different recipient for V2.1.
FEE_RECIPIENT=0xe0f9615B8C63574eB9c0CAf22438Daa4Ac911A03
INSURANCE_POOL=0xe0f9615B8C63574eB9c0CAf22438Daa4Ac911A03

RPC=https://sepolia.base.org
CAST=/root/.foundry/bin/cast
FORGE=/root/.foundry/bin/forge

echo "════════════════════════════════════════════════════════════"
echo "  Sprint 53 / Phase A.1  $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo "  AgoraEscrowV21 deploy to Base Sepolia"
echo "════════════════════════════════════════════════════════════"

# 1) Repo auf neuesten Stand (auto-pull lässt contracts/ liegen)
cd /opt/agora
git fetch --tags 2>&1 | tail -5 || true
git checkout main
git pull --ff-only origin main 2>&1 | tail -3

# 2) Submodules sicherstellen
cd contracts
git submodule update --init --recursive 2>&1 | tail -3

# 3) Load deployer + Basescan key
# PRIVATE_KEY from the dedicated .deployer-key file (mode 600); .env has
# BASESCAN_API_KEY + Anthropic key etc.
set +u
source /opt/agora/experiments/swarm/.env
set -u

DEPLOYER_KEY_FILE=/opt/agora/experiments/swarm/.deployer-key
if [ ! -f "$DEPLOYER_KEY_FILE" ]; then
    echo "ERROR: $DEPLOYER_KEY_FILE not found"
    exit 1
fi
PRIVATE_KEY=$(cat "$DEPLOYER_KEY_FILE" | tr -d '[:space:]')
[[ "$PRIVATE_KEY" != 0x* ]] && PRIVATE_KEY="0x$PRIVATE_KEY"
export PRIVATE_KEY

# BASESCAN_API_KEY fallback search (same pattern as sprint45-deploy-timelock.sh)
if [ -z "${BASESCAN_API_KEY:-}" ]; then
    for f in /opt/agora/apps/backend/.env \
             /opt/agora/.env \
             /opt/agora/experiments/swarm/.basescan-key \
             /root/.basescan-key; do
        if [ -f "$f" ]; then
            if grep -q "^BASESCAN_API_KEY=" "$f" 2>/dev/null; then
                set +u; source <(grep "^BASESCAN_API_KEY=" "$f"); set -u
                echo "  BASESCAN_API_KEY loaded from $f"
                break
            elif [ "$(wc -l < "$f")" -le 2 ]; then
                BASESCAN_API_KEY=$(cat "$f" | tr -d '[:space:]')
                echo "  BASESCAN_API_KEY loaded from $f (bare-key file)"
                break
            fi
        fi
    done
fi

VERIFY_FLAGS=""
if [ -n "${BASESCAN_API_KEY:-}" ]; then
    VERIFY_FLAGS="--verify --etherscan-api-key $BASESCAN_API_KEY"
    echo "  BASESCAN_API_KEY: set (verify enabled)"
else
    echo "  BASESCAN_API_KEY: NOT FOUND -- deploying WITHOUT --verify"
    echo "  Verify command will be printed at the end."
fi

# Export the DeployV21.s.sol-required env vars
export USDC_ADDRESS USDC_DECIMALS FEE_RECIPIENT INSURANCE_POOL

# 4) Pre-flight
DEPLOYER=$($CAST wallet address --private-key "$PRIVATE_KEY")
DEPLOYER_ETH=$($CAST balance $DEPLOYER --rpc-url $RPC | awk '{print $1}')

echo ""
echo "=== Pre-flight ==="
echo "  Repo HEAD:       $(git -C /opt/agora rev-parse HEAD)"
echo "  Repo tag:        $(git -C /opt/agora describe --tags --always)"
echo "  USDC:            $USDC_ADDRESS (Base Sepolia)"
echo "  USDC decimals:   $USDC_DECIMALS"
echo "  Fee recipient:   $FEE_RECIPIENT"
echo "  Insurance pool:  $INSURANCE_POOL"
echo "  Deployer:        $DEPLOYER"
echo "  Deployer ETH:    $DEPLOYER_ETH wei"
echo ""

# Sanity: V2.1 source must exist where we expect it
if [ ! -f src/AgoraEscrowV21.sol ]; then
    echo "ERROR: contracts/src/AgoraEscrowV21.sol not found at expected path."
    echo "Did the V2.1 spike (Sprint 47) land cleanly?"
    exit 1
fi

if [ ! -f script/DeployV21.s.sol ]; then
    echo "ERROR: contracts/script/DeployV21.s.sol not found."
    echo "Did Sprint 48 land cleanly?"
    exit 1
fi

# Refuse if ETH balance is too low for a V2.1 contract deploy.
# V2.1 is ~360 lines, expect similar gas to V2 = ~3-4M gas on cold deploy.
# 4M * 0.01 gwei = 4e13 wei = 0.00004 ETH. Threshold = 10x = 0.0004 ETH.
MIN_WEI=400000000000000  # 0.0004 ETH
if [ "$DEPLOYER_ETH" -lt "$MIN_WEI" ]; then
    echo "ERROR: Deployer has < 0.0004 ETH on Sepolia. Refusing to deploy."
    echo "Fund $DEPLOYER on Sepolia first."
    exit 1
fi

# Make sure V2.1 tests are green at this exact revision -- if forge can't
# compile or the test suite fails, deploying is reckless.
echo "=== Pre-deploy: forge build + test on V21 source ==="
$FORGE build --skip "*.t.sol" 2>&1 | tail -5
$FORGE test --match-contract AgoraEscrowV21Test 2>&1 | tail -10
$FORGE test --match-contract AgoraEscrowV21TimelockTest 2>&1 | tail -10

# 5) Deploy (+ verify if BASESCAN_API_KEY was found)
echo ""
echo "=== Broadcasting V2.1 deploy ==="
# shellcheck disable=SC2086
$FORGE script script/DeployV21.s.sol:DeployV21 \
  --rpc-url $RPC \
  --broadcast \
  $VERIFY_FLAGS \
  -vv

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  V2.1 deploy done."
if [ -z "${BASESCAN_API_KEY:-}" ]; then
    echo ""
    echo "  Verify was SKIPPED. To verify later:"
    echo ""
    echo "    cd /opt/agora/contracts && \\"
    echo "    /root/.foundry/bin/forge verify-contract \\"
    echo "      --chain base_sepolia \\"
    echo "      <V21_ADDR_FROM_OUTPUT_ABOVE> \\"
    echo "      src/AgoraEscrowV21.sol:AgoraEscrowV21 \\"
    echo "      --constructor-args \$(/root/.foundry/bin/cast abi-encode \\"
    echo "        \"constructor(address,uint8,address,address)\" \\"
    echo "        $USDC_ADDRESS $USDC_DECIMALS $FEE_RECIPIENT $INSURANCE_POOL) \\"
    echo "      --etherscan-api-key \$BASESCAN_API_KEY"
fi
echo ""
echo "  Next: paste the 'AgoraEscrowV21 deployed at:' line back so we can"
echo "  build Phase A.2 (setPauser + setDisputeResolver via Safe-admin-op)."
echo "════════════════════════════════════════════════════════════"
