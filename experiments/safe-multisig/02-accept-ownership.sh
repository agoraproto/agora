#!/usr/bin/env bash
# Sprint 37c — Safe.execTransaction → V2.acceptOwnership() with 2-of-2 EIP-712 sigs
#
# Pre-conditions (Sprint 37a+b done):
#   - Safe 0x8ec63... deployed, 2-of-2 with cosigner #1 + #2
#   - V2.pendingOwner() = Safe (transferOwnership initiated by deployer)
#
# This script:
#   1. Re-verifies pre-conditions
#   2. Builds the Safe transaction for V2.acceptOwnership() (selector 0x79ba5097)
#   3. Computes EIP-712 SafeTxHash (domain = chainId 84532 + verifyingContract = Safe)
#   4. Signs the hash with cosigner #1 AND cosigner #2
#   5. Packs sigs sorted ASC by signer address (Safe convention)
#   6. Broadcasts Safe.execTransaction from deployer (deployer pays gas only)
#   7. Verifies V2.owner() now == Safe
#
# Irreversible: after this, V2 is exclusively controlled by the Safe.

V2=0x0e8E6A760c76cA92c5C5dA06d293E33f1B5fbAEc
RPC=https://sepolia.base.org
CAST=/root/.foundry/bin/cast
PYTHON=/opt/agora/apps/backend/.venv/bin/python3

SAFE_DIR=/opt/agora/experiments/safe-multisig
COSIGNER1_FILE=$SAFE_DIR/.cosigner-1
COSIGNER2_FILE=$SAFE_DIR/.cosigner-2
SAFE_ADDR_FILE=$SAFE_DIR/.safe-address
DEPLOYER_KEY_FILE=/opt/agora/experiments/swarm/.deployer-key

SAFE=$(cat $SAFE_ADDR_FILE | tr -d '[:space:]')
COSIGNER1_KEY=$(cat $COSIGNER1_FILE | tr -d '[:space:]')
COSIGNER2_KEY=$(cat $COSIGNER2_FILE | tr -d '[:space:]')
DEPLOYER_KEY=$(cat $DEPLOYER_KEY_FILE | tr -d '[:space:]')

[[ "$COSIGNER1_KEY" != 0x* ]] && COSIGNER1_KEY="0x$COSIGNER1_KEY"
[[ "$COSIGNER2_KEY" != 0x* ]] && COSIGNER2_KEY="0x$COSIGNER2_KEY"
[[ "$DEPLOYER_KEY" != 0x* ]] && DEPLOYER_KEY="0x$DEPLOYER_KEY"

echo "============================================================"
echo "  Sprint 37c — Safe accepts V2 ownership"
echo "  $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo "============================================================"
echo "  Safe: $SAFE"
echo "  V2:   $V2"

# ── [1/4] Pre-flight ──────────────────────────────────────────────
echo ""
echo "=== [1/4] Pre-flight ==="
CURRENT_OWNER=$($CAST call $V2 "owner()(address)" --rpc-url $RPC)
CURRENT_PENDING=$($CAST call $V2 "pendingOwner()(address)" --rpc-url $RPC)
echo "  V2.owner() before:        $CURRENT_OWNER"
echo "  V2.pendingOwner() before: $CURRENT_PENDING"

SAFE_LC=$(echo $SAFE | tr 'A-Z' 'a-z')
PENDING_LC=$(echo $CURRENT_PENDING | tr 'A-Z' 'a-z')
if [ "$SAFE_LC" != "$PENDING_LC" ]; then
    echo "  ! pendingOwner is not the Safe — aborting (run sprint37-safe-deploy.sh first)"
    exit 1
fi
echo "  ✓ pendingOwner = Safe"

NONCE=$($CAST call $SAFE "nonce()(uint256)" --rpc-url $RPC)
echo "  Safe nonce: $NONCE"

# ── [2/4] EIP-712 sign + build execTransaction call ───────────────
echo ""
echo "=== [2/4] Build SafeTx, sign with both cosigners, broadcast ==="

$PYTHON - "$SAFE" "$V2" "$NONCE" "$COSIGNER1_KEY" "$COSIGNER2_KEY" "$DEPLOYER_KEY" "$RPC" <<'PYEOF'
import sys
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_typed_data

SAFE = Web3.to_checksum_address(sys.argv[1])
V2 = Web3.to_checksum_address(sys.argv[2])
NONCE = int(sys.argv[3])
COSIGNER1_KEY = sys.argv[4]
COSIGNER2_KEY = sys.argv[5]
DEPLOYER_KEY = sys.argv[6]
RPC = sys.argv[7]
CHAIN_ID = 84532

w3 = Web3(Web3.HTTPProvider(RPC))

# acceptOwnership() selector
ACCEPT_OWNERSHIP_DATA = bytes.fromhex("79ba5097")

# SafeTx fields (zero-fee/zero-gas — relayer pays directly)
safe_tx = {
    "to": V2,
    "value": 0,
    "data": ACCEPT_OWNERSHIP_DATA,
    "operation": 0,
    "safeTxGas": 0,
    "baseGas": 0,
    "gasPrice": 0,
    "gasToken": "0x0000000000000000000000000000000000000000",
    "refundReceiver": "0x0000000000000000000000000000000000000000",
    "nonce": NONCE,
}

eip712 = {
    "types": {
        "EIP712Domain": [
            {"name": "chainId", "type": "uint256"},
            {"name": "verifyingContract", "type": "address"},
        ],
        "SafeTx": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
            {"name": "operation", "type": "uint8"},
            {"name": "safeTxGas", "type": "uint256"},
            {"name": "baseGas", "type": "uint256"},
            {"name": "gasPrice", "type": "uint256"},
            {"name": "gasToken", "type": "address"},
            {"name": "refundReceiver", "type": "address"},
            {"name": "nonce", "type": "uint256"},
        ],
    },
    "domain": {"chainId": CHAIN_ID, "verifyingContract": SAFE},
    "primaryType": "SafeTx",
    "message": safe_tx,
}

signable = encode_typed_data(full_message=eip712)
print(f"  SafeTxHash: 0x{signable.body.hex()}")

acc1 = Account.from_key(COSIGNER1_KEY)
acc2 = Account.from_key(COSIGNER2_KEY)
print(f"  Cosigner1 ({acc1.address}) signing...")
sig1 = Account.sign_message(signable, COSIGNER1_KEY)
print(f"  Cosigner2 ({acc2.address}) signing...")
sig2 = Account.sign_message(signable, COSIGNER2_KEY)

# Pack sorted ASC by signer address (Safe checkSignatures requirement)
pairs = sorted(
    [(acc1.address, sig1), (acc2.address, sig2)],
    key=lambda x: int(x[0], 16),
)
packed = b""
for addr, s in pairs:
    packed += s.r.to_bytes(32, "big") + s.s.to_bytes(32, "big") + s.v.to_bytes(1, "big")
print(f"  Packed sigs ({len(packed)} bytes): 0x{packed.hex()[:80]}...")

# Build + broadcast execTransaction
safe_abi = [{
    "name": "execTransaction",
    "type": "function",
    "inputs": [
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "data", "type": "bytes"},
        {"name": "operation", "type": "uint8"},
        {"name": "safeTxGas", "type": "uint256"},
        {"name": "baseGas", "type": "uint256"},
        {"name": "gasPrice", "type": "uint256"},
        {"name": "gasToken", "type": "address"},
        {"name": "refundReceiver", "type": "address"},
        {"name": "signatures", "type": "bytes"},
    ],
    "outputs": [{"name": "", "type": "bool"}],
    "stateMutability": "payable",
}]

safe_contract = w3.eth.contract(address=SAFE, abi=safe_abi)
relayer = Account.from_key(DEPLOYER_KEY)
gas_price = max(w3.eth.gas_price * 2, w3.to_wei(0.05, "gwei"))

tx = safe_contract.functions.execTransaction(
    safe_tx["to"], safe_tx["value"], safe_tx["data"], safe_tx["operation"],
    safe_tx["safeTxGas"], safe_tx["baseGas"], safe_tx["gasPrice"],
    safe_tx["gasToken"], safe_tx["refundReceiver"], packed,
).build_transaction({
    "from": relayer.address,
    "nonce": w3.eth.get_transaction_count(relayer.address),
    "gas": 300_000,
    "gasPrice": gas_price,
    "chainId": CHAIN_ID,
})

print(f"  Broadcasting Safe.execTransaction (relayer = deployer)...")
signed = relayer.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"  tx: 0x{tx_hash.hex()}")
receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
print(f"  status: {receipt.status}  block: {receipt.blockNumber}  gasUsed: {receipt.gasUsed}")
if receipt.status != 1:
    print(f"  ! Tx reverted — aborting verify phase")
    sys.exit(1)
PYEOF
PYRC=$?
if [ $PYRC -ne 0 ]; then
    echo "  ! Python exited $PYRC"
    exit 1
fi

# ── [3/4] Verify V2 ownership flipped ─────────────────────────────
echo ""
echo "=== [3/4] Verify ==="
NEW_OWNER=$($CAST call $V2 "owner()(address)" --rpc-url $RPC)
NEW_PENDING=$($CAST call $V2 "pendingOwner()(address)" --rpc-url $RPC)
echo "  V2.owner() after:        $NEW_OWNER"
echo "  V2.pendingOwner() after: $NEW_PENDING"

NEW_OWNER_LC=$(echo $NEW_OWNER | tr 'A-Z' 'a-z')
if [ "$NEW_OWNER_LC" = "$SAFE_LC" ]; then
    echo "  ✓ V2 ownership transferred to Safe — multisig now controls V2"
else
    echo "  ! V2 owner is not the Safe — something went wrong"
    exit 1
fi

# Verify Safe nonce incremented
NEW_NONCE=$($CAST call $SAFE "nonce()(uint256)" --rpc-url $RPC)
echo "  Safe nonce: $NONCE → $NEW_NONCE"

echo ""
echo "=== [4/4] Sanity smoke ==="
echo "  V2 fee state (should be unchanged):"
echo -n "    feeBps:  "
$CAST call $V2 "feeBps()(uint16)" --rpc-url $RPC
echo -n "    minFee:  "
$CAST call $V2 "minFee()(uint256)" --rpc-url $RPC
echo -n "    paused:  "
$CAST call $V2 "paused()(bool)" --rpc-url $RPC

echo ""
echo "============================================================"
echo "  Sprint 37c done."
echo ""
echo "  V2 owner: $NEW_OWNER (= Safe)"
echo "  Deployer EOA can NO LONGER call setFees/pause/setFeeRecipient."
echo "  Future admin tx → Safe.execTransaction(target, value, data, ..., sigs)"
echo "  with 2-of-2 cosigner signatures."
echo "============================================================"
