#!/usr/bin/env bash
# Sprint 37a+b — Deploy 2-of-2 Safe on Base Sepolia, then V2.transferOwnership(safe)
#
# Idempotent: re-running just verifies state without redoing things.
# Cosigner keys persist at /opt/agora/experiments/safe-multisig/.cosigner-{1,2}
#
# Phases:
#   1) Validate Safe contracts exist on Base Sepolia
#   2) Generate or load cosigner keys (mode 600)
#   3) Deploy 2-of-2 Safe via SafeProxyFactory
#   4) V2.transferOwnership(safe) — initiates Ownable2Step handoff
#   5) Verify state

V2=0x0e8E6A760c76cA92c5C5dA06d293E33f1B5fbAEc
RPC=https://sepolia.base.org
CAST=/root/.foundry/bin/cast
DEPLOYER_KEY_FILE=/opt/agora/experiments/swarm/.deployer-key

# Safe v1.4.1 official deployments — same address on every chain (CREATE2)
SAFE_FACTORY=0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67
SAFE_SINGLETON_L2=0x29fcB43b46531BcA003ddC8FCB67FFE91900C762
SAFE_FALLBACK=0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99

SAFE_DIR=/opt/agora/experiments/safe-multisig
COSIGNER1_FILE=$SAFE_DIR/.cosigner-1
COSIGNER2_FILE=$SAFE_DIR/.cosigner-2
SAFE_ADDR_FILE=$SAFE_DIR/.safe-address

mkdir -p "$SAFE_DIR"
chmod 700 "$SAFE_DIR"

DEPLOYER_KEY=$(cat "$DEPLOYER_KEY_FILE" | tr -d '[:space:]')
[[ "$DEPLOYER_KEY" != 0x* ]] && DEPLOYER_KEY="0x$DEPLOYER_KEY"
DEPLOYER_ADDR=$($CAST wallet address --private-key "$DEPLOYER_KEY")

echo "============================================================"
echo "  Sprint 37a+b — Safe Multisig setup for V2"
echo "  $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo "============================================================"
echo "  V2:        $V2"
echo "  Deployer:  $DEPLOYER_ADDR"

# ── Phase 1: Validate Safe deployments exist on Base Sepolia ──────
echo ""
echo "=== [1/5] Validate Safe v1.4.1 contracts on Base Sepolia ==="
for ADDR in $SAFE_FACTORY $SAFE_SINGLETON_L2 $SAFE_FALLBACK; do
    CODE=$($CAST code "$ADDR" --rpc-url "$RPC")
    SIZE=${#CODE}
    if [ "$SIZE" -lt 4 ]; then
        echo "  ! $ADDR has no code on Base Sepolia — aborting"
        echo "  Check https://docs.safe.global/advanced/smart-account-supported-networks"
        exit 1
    fi
    echo "  $ADDR has code ($SIZE bytes) -> OK"
done

# ── Phase 2: Generate or load cosigner keys ──────────────────────
echo ""
echo "=== [2/5] Cosigner keys ==="
if [ ! -s "$COSIGNER1_FILE" ]; then
    $CAST wallet new --json | python3 -c "import json,sys; d=json.load(sys.stdin)[0]; open('$COSIGNER1_FILE','w').write(d['private_key'])"
    chmod 600 "$COSIGNER1_FILE"
    echo "  + generated cosigner #1"
else
    echo "  - cosigner #1 already exists"
fi
if [ ! -s "$COSIGNER2_FILE" ]; then
    $CAST wallet new --json | python3 -c "import json,sys; d=json.load(sys.stdin)[0]; open('$COSIGNER2_FILE','w').write(d['private_key'])"
    chmod 600 "$COSIGNER2_FILE"
    echo "  + generated cosigner #2"
else
    echo "  - cosigner #2 already exists"
fi

COSIGNER1_KEY=$(cat "$COSIGNER1_FILE" | tr -d '[:space:]')
[[ "$COSIGNER1_KEY" != 0x* ]] && COSIGNER1_KEY="0x$COSIGNER1_KEY"
COSIGNER1_ADDR=$($CAST wallet address --private-key "$COSIGNER1_KEY")
COSIGNER2_KEY=$(cat "$COSIGNER2_FILE" | tr -d '[:space:]')
[[ "$COSIGNER2_KEY" != 0x* ]] && COSIGNER2_KEY="0x$COSIGNER2_KEY"
COSIGNER2_ADDR=$($CAST wallet address --private-key "$COSIGNER2_KEY")
echo "  cosigner #1: $COSIGNER1_ADDR"
echo "  cosigner #2: $COSIGNER2_ADDR"

# Sort cosigner addresses ascending (Safe convention; also strictly required for sig assembly later)
SORTED=$(python3 -c "
a1 = '$COSIGNER1_ADDR'.lower()
a2 = '$COSIGNER2_ADDR'.lower()
if a1 < a2:
    print(a1 + ' ' + a2)
else:
    print(a2 + ' ' + a1)
")
SORTED_C1=$(echo "$SORTED" | awk '{print $1}')
SORTED_C2=$(echo "$SORTED" | awk '{print $2}')

# ── Phase 3: Deploy 2-of-2 Safe (skip if already deployed) ───────
echo ""
echo "=== [3/5] Deploy 2-of-2 Safe via ProxyFactory ==="

EXISTING_SAFE=""
if [ -s "$SAFE_ADDR_FILE" ]; then
    EXISTING_SAFE=$(cat "$SAFE_ADDR_FILE" | tr -d '[:space:]')
    EXISTING_CODE=$($CAST code "$EXISTING_SAFE" --rpc-url "$RPC")
    if [ ${#EXISTING_CODE} -gt 4 ]; then
        echo "  - Safe already deployed at $EXISTING_SAFE"
        SAFE_ADDR=$EXISTING_SAFE
    else
        EXISTING_SAFE=""
    fi
fi

if [ -z "$EXISTING_SAFE" ]; then
    # Build setup() calldata
    SETUP_CALLDATA=$($CAST calldata "setup(address[],uint256,address,bytes,address,address,uint256,address)" \
        "[$SORTED_C1,$SORTED_C2]" \
        2 \
        0x0000000000000000000000000000000000000000 \
        0x \
        $SAFE_FALLBACK \
        0x0000000000000000000000000000000000000000 \
        0 \
        0x0000000000000000000000000000000000000000)
    echo "  setup() calldata: ${SETUP_CALLDATA:0:50}..."

    # Random salt nonce
    SALT_NONCE=$(date +%s%N)
    echo "  saltNonce: $SALT_NONCE"

    echo "  Broadcasting createProxyWithNonce..."
    TX_HASH=$($CAST send \
        --rpc-url "$RPC" \
        --private-key "$DEPLOYER_KEY" \
        $SAFE_FACTORY \
        "createProxyWithNonce(address,bytes,uint256)" \
        $SAFE_SINGLETON_L2 \
        "$SETUP_CALLDATA" \
        "$SALT_NONCE" \
        --json | python3 -c "import json,sys; print(json.load(sys.stdin)['transactionHash'])")
    echo "  tx: $TX_HASH"
    sleep 5

    # Parse ProxyCreation event (proxy is indexed → topic1)
    SAFE_ADDR=$($CAST receipt $TX_HASH --rpc-url $RPC --json | python3 -c "
import json, sys
r = json.load(sys.stdin)
# ProxyCreation(SafeProxy indexed proxy, address singleton) on the factory
PROXY_CREATION_SIG = '0x4f51faf6c4561ff95f067657e43439f0f856d97c04d9ec9070a6199ad418e235'
for log in r.get('logs', []):
    topics = log.get('topics', [])
    if topics and topics[0].lower() == PROXY_CREATION_SIG and log['address'].lower() == '$SAFE_FACTORY'.lower():
        print('0x' + topics[1][-40:])
        break
")
    if [ -z "$SAFE_ADDR" ]; then
        echo "  ! Could not parse Safe address from receipt"
        exit 1
    fi
    echo "  + Safe deployed at: $SAFE_ADDR"
    echo "$SAFE_ADDR" > "$SAFE_ADDR_FILE"
fi

# Verify Safe state
echo "  Verifying Safe..."
echo -n "    threshold: "
$CAST call $SAFE_ADDR "getThreshold()(uint256)" --rpc-url $RPC
echo -n "    owners:    "
$CAST call $SAFE_ADDR "getOwners()(address[])" --rpc-url $RPC

# ── Phase 4: V2.transferOwnership(safe) ───────────────────────────
echo ""
echo "=== [4/5] V2.transferOwnership(safe) ==="
CURRENT_PENDING=$($CAST call $V2 "pendingOwner()(address)" --rpc-url $RPC)
CURRENT_OWNER=$($CAST call $V2 "owner()(address)" --rpc-url $RPC)
echo "  V2.owner() before:        $CURRENT_OWNER"
echo "  V2.pendingOwner() before: $CURRENT_PENDING"

if [ "${CURRENT_PENDING,,}" = "${SAFE_ADDR,,}" ]; then
    echo "  - pendingOwner already = Safe, skipping transferOwnership"
else
    echo "  Broadcasting V2.transferOwnership($SAFE_ADDR)..."
    TX=$($CAST send \
        --rpc-url $RPC \
        --private-key "$DEPLOYER_KEY" \
        $V2 \
        "transferOwnership(address)" \
        $SAFE_ADDR \
        --json | python3 -c "import json,sys; print(json.load(sys.stdin)['transactionHash'])")
    echo "  tx: $TX"
    sleep 5
fi

# ── Phase 5: Final verify ─────────────────────────────────────────
echo ""
echo "=== [5/5] Final state ==="
NEW_OWNER=$($CAST call $V2 "owner()(address)" --rpc-url $RPC)
NEW_PENDING=$($CAST call $V2 "pendingOwner()(address)" --rpc-url $RPC)
echo "  V2.owner():        $NEW_OWNER"
echo "  V2.pendingOwner(): $NEW_PENDING"
echo ""
if [ "${NEW_PENDING,,}" = "${SAFE_ADDR,,}" ]; then
    echo "  ✓ Ownership transfer INITIATED — Safe is now pendingOwner"
    echo "  ✓ Owner still = Deployer (until Sprint 37c acceptOwnership)"
    echo "  ✓ Reversible: deployer can call transferOwnership(other) until Safe accepts"
else
    echo "  ! Unexpected pendingOwner state"
fi

echo ""
echo "============================================================"
echo "  Sprint 37a+b done."
echo ""
echo "  Safe:        $SAFE_ADDR"
echo "  Cosigner #1: $COSIGNER1_ADDR"
echo "  Cosigner #2: $COSIGNER2_ADDR"
echo ""
echo "  Basescan:    https://sepolia.basescan.org/address/$SAFE_ADDR"
echo "  Safe UI:     https://app.safe.global/home?safe=basesep:$SAFE_ADDR"
echo ""
echo "  NEXT (Sprint 37c): Safe must call V2.acceptOwnership() with 2-of-2"
echo "  signatures. Plan: build EIP-712 Safe tx hash, sign with cosigner #1 + #2,"
echo "  call Safe.execTransaction(V2, 0, acceptOwnership calldata, ...)."
echo "============================================================"
