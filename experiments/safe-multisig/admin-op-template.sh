#!/usr/bin/env bash
# safe-admin-op.sh — execute ANY target-contract function via the 2-of-2 Safe.
#
# HOW TO USE:
#   1. Edit the CONFIGURATION block below (TARGET + CALLDATA + DRY_RUN)
#   2. First run with DRY_RUN=1 (default) — preview, no broadcast
#   3. Once preview looks correct, set DRY_RUN=0 and re-run — actually broadcasts
#
#   Get-Content C:\Users\WAVO\Desktop\Projekte\agor\safe-admin-op.sh -Raw | ssh root@188.245.39.250 bash
#
# WHAT IT DOES:
#   * Loads Safe address + both cosigner keys from /opt/agora/experiments/safe-multisig/
#   * Builds a SafeTx for TARGET.call(CALLDATA) with current Safe nonce
#   * EIP-712 signs with cosigner #1 AND cosigner #2
#   * Packs sigs sorted ASC by signer address (Safe requirement)
#   * Preview mode: prints SafeTxHash + sigs + simulates the call
#   * Execute mode: broadcasts Safe.execTransaction from the deployer as gas relayer
#
# RECOVERY: if you broadcast something wrong, just edit + re-run with a different
# CALLDATA. Cosigner keys, Safe, V2 — none are affected by a failed admin call.

# ─────────────────────────────────────────────────────────────────
# === CONFIGURATION — EDIT THESE FOR YOUR OPERATION ===
# ─────────────────────────────────────────────────────────────────

# Set to 0 to actually broadcast. Default 1 = preview only.
DRY_RUN=${DRY_RUN:-1}

# Target contract (default: V2 escrow)
TARGET=${TARGET:-0x0e8E6A760c76cA92c5C5dA06d293E33f1B5fbAEc}

# ETH to send with the call (default 0)
TARGET_VALUE=${TARGET_VALUE:-0}

# The function call calldata — built via `cast calldata "sig(types...)" args...`
# Edit ONE of the examples below, or write your own.
#
# Defaults to a setFees probe with the CURRENT production values, which is a
# semantic no-op you can broadcast safely to verify the Safe→V2 path works.
CAST=/root/.foundry/bin/cast

# ════════════════════════════════════════════════════════════════
# EXAMPLES — uncomment ONE and comment the others
# ════════════════════════════════════════════════════════════════

# 1) Reset fees to current production values (semantic no-op probe):
CALLDATA=$($CAST calldata "setFees(uint16,uint256,uint256,uint16)" 10 0 25000000 1000)

# 2) Emergency pause (Sprint 35 L-01: V2 has OZ Pausable):
# CALLDATA=$($CAST calldata "pause()")

# 3) Unpause:
# CALLDATA=$($CAST calldata "unpause()")

# 4) Change the fee recipient (where the platform fee accumulates):
# CALLDATA=$($CAST calldata "setFeeRecipient(address)" 0x0000000000000000000000000000000000000000)

# 5) Change the insurance pool:
# CALLDATA=$($CAST calldata "setInsurancePool(address)" 0x0000000000000000000000000000000000000000)

# 6) Add a new owner to the Safe itself (TARGET would be the Safe address):
# TARGET=0x8ec63fe30dab84308b5009b8d91d9e4deb5a61fc
# CALLDATA=$($CAST calldata "addOwnerWithThreshold(address,uint256)" 0xYourHardwareWalletHere 2)

# 7) Change Safe threshold (e.g. raise from 2-of-2 to 2-of-3 after adding owner):
# TARGET=0x8ec63fe30dab84308b5009b8d91d9e4deb5a61fc
# CALLDATA=$($CAST calldata "changeThreshold(uint256)" 2)

# ─────────────────────────────────────────────────────────────────
# Below this line: no config needed
# ─────────────────────────────────────────────────────────────────

RPC=https://sepolia.base.org
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

echo "════════════════════════════════════════════════════════════"
echo "  Safe Admin Op  $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo "════════════════════════════════════════════════════════════"
echo "  Mode:       $([ "$DRY_RUN" = "1" ] && echo "DRY RUN (no broadcast)" || echo "EXECUTE (broadcasts)")"
echo "  Safe:       $SAFE"
echo "  Target:     $TARGET"
echo "  Value:      $TARGET_VALUE wei"
echo "  Calldata:   $CALLDATA"

# ── Pre-flight ───────────────────────────────────────────────────
echo ""
echo "=== Pre-flight ==="
NONCE=$($CAST call $SAFE "nonce()(uint256)" --rpc-url $RPC)
THRESHOLD=$($CAST call $SAFE "getThreshold()(uint256)" --rpc-url $RPC)
TARGET_CODE=$($CAST code $TARGET --rpc-url $RPC)
TARGET_CODE_LEN=${#TARGET_CODE}
echo "  Safe nonce:      $NONCE"
echo "  Safe threshold:  $THRESHOLD"
echo "  Target has code: $([ $TARGET_CODE_LEN -gt 4 ] && echo "YES ($TARGET_CODE_LEN bytes)" || echo "NO — call would do nothing!")"

# ── Build SafeTx + sign with both cosigners ──────────────────────
echo ""
echo "=== Build SafeTx + EIP-712 sign with cosigner #1 + #2 ==="

OUT=$($PYTHON - "$SAFE" "$TARGET" "$TARGET_VALUE" "$CALLDATA" "$NONCE" "$COSIGNER1_KEY" "$COSIGNER2_KEY" "$DEPLOYER_KEY" "$RPC" "$DRY_RUN" <<'PYEOF'
import sys, json
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_typed_data

SAFE = Web3.to_checksum_address(sys.argv[1])
TARGET = Web3.to_checksum_address(sys.argv[2])
VALUE = int(sys.argv[3])
CALLDATA_HEX = sys.argv[4]
NONCE = int(sys.argv[5])
COSIGNER1_KEY = sys.argv[6]
COSIGNER2_KEY = sys.argv[7]
DEPLOYER_KEY = sys.argv[8]
RPC = sys.argv[9]
DRY_RUN = sys.argv[10] == "1"
CHAIN_ID = 84532

w3 = Web3(Web3.HTTPProvider(RPC))

# Strip 0x and decode
data_bytes = bytes.fromhex(CALLDATA_HEX[2:] if CALLDATA_HEX.startswith("0x") else CALLDATA_HEX)

safe_tx = {
    "to": TARGET,
    "value": VALUE,
    "data": data_bytes,
    "operation": 0,  # CALL
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
acc1 = Account.from_key(COSIGNER1_KEY)
acc2 = Account.from_key(COSIGNER2_KEY)
sig1 = Account.sign_message(signable, COSIGNER1_KEY)
sig2 = Account.sign_message(signable, COSIGNER2_KEY)

# Pack sorted ASC by signer address
pairs = sorted([(acc1.address, sig1), (acc2.address, sig2)], key=lambda x: int(x[0], 16))
packed = b"".join(
    s.r.to_bytes(32, "big") + s.s.to_bytes(32, "big") + s.v.to_bytes(1, "big")
    for _, s in pairs
)

# Simulate via eth_call before commit — catches reverts cheaply
safe_abi = [{
    "name": "execTransaction", "type": "function", "stateMutability": "payable",
    "inputs": [
        {"name": "to", "type": "address"}, {"name": "value", "type": "uint256"},
        {"name": "data", "type": "bytes"}, {"name": "operation", "type": "uint8"},
        {"name": "safeTxGas", "type": "uint256"}, {"name": "baseGas", "type": "uint256"},
        {"name": "gasPrice", "type": "uint256"}, {"name": "gasToken", "type": "address"},
        {"name": "refundReceiver", "type": "address"}, {"name": "signatures", "type": "bytes"},
    ],
    "outputs": [{"name": "", "type": "bool"}],
}]
safe_c = w3.eth.contract(address=SAFE, abi=safe_abi)
relayer = Account.from_key(DEPLOYER_KEY)

result = {
    "safe_tx_hash_body": "0x" + signable.body.hex(),
    "cosigner1": acc1.address,
    "cosigner2": acc2.address,
    "packed_sigs": "0x" + packed.hex(),
    "packed_len": len(packed),
}

# Try a static eth_call to catch obvious reverts before broadcasting
try:
    sim_result = safe_c.functions.execTransaction(
        safe_tx["to"], safe_tx["value"], safe_tx["data"], safe_tx["operation"],
        safe_tx["safeTxGas"], safe_tx["baseGas"], safe_tx["gasPrice"],
        safe_tx["gasToken"], safe_tx["refundReceiver"], packed,
    ).call({"from": relayer.address})
    result["simulation"] = "success" if sim_result else "execTransaction returned false (inner call reverted but no GS013)"
except Exception as e:
    msg = str(e)
    if "GS026" in msg:
        result["simulation"] = "FAIL — GS026: signature check failed (sigs don't match the SafeTxHash)"
    elif "GS013" in msg:
        result["simulation"] = "FAIL — GS013: inner call reverted (safeTxGas=0 && gasPrice=0 requires inner success)"
    else:
        result["simulation"] = f"FAIL — {msg[:200]}"

if DRY_RUN:
    print(json.dumps(result, indent=2))
    sys.exit(0)

# Broadcast
gas_price = max(w3.eth.gas_price * 2, w3.to_wei(0.05, "gwei"))
tx = safe_c.functions.execTransaction(
    safe_tx["to"], safe_tx["value"], safe_tx["data"], safe_tx["operation"],
    safe_tx["safeTxGas"], safe_tx["baseGas"], safe_tx["gasPrice"],
    safe_tx["gasToken"], safe_tx["refundReceiver"], packed,
).build_transaction({
    "from": relayer.address,
    "nonce": w3.eth.get_transaction_count(relayer.address),
    "gas": 500_000,
    "gasPrice": gas_price,
    "chainId": CHAIN_ID,
})
signed = relayer.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
result["broadcast_tx"] = "0x" + tx_hash.hex()
print(json.dumps(result, indent=2))

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
result["receipt_status"] = receipt.status
result["receipt_block"] = receipt.blockNumber
result["receipt_gas_used"] = receipt.gasUsed
print(json.dumps({k: result[k] for k in ("broadcast_tx", "receipt_status", "receipt_block", "receipt_gas_used")}, indent=2))

# Check for ExecutionSuccess vs ExecutionFailure
EXEC_SUCCESS = "0x442e715f626346e8c54381002da614f62bee8d27386535b2521ec8540898556e"
EXEC_FAILURE = "0x23428b18acfb3ea64b08dc0c1d296ea9c09702c09083ca5272e64d115b687d23"
for log in receipt.logs:
    if not log.topics:
        continue
    t0 = log.topics[0].hex().lower()
    if t0 == EXEC_SUCCESS.lower():
        print("Event: ExecutionSuccess — Safe completed the tx and the inner call succeeded")
    elif t0 == EXEC_FAILURE.lower():
        print("Event: ExecutionFailure — Safe ran but inner call reverted (state unchanged)")
PYEOF
)
echo "$OUT"

echo ""
if [ "$DRY_RUN" = "1" ]; then
    echo "════════════════════════════════════════════════════════════"
    echo "  DRY RUN COMPLETE — nothing was broadcast"
    echo ""
    echo "  Read 'simulation' field above:"
    echo "    success  -> safe to re-run with DRY_RUN=0"
    echo "    FAIL ... -> fix the issue, do NOT execute"
    echo ""
    echo "  To actually broadcast, edit the DRY_RUN line at the top of"
    echo "  this script to set it to 0, then re-pipe via Get-Content."
    echo "════════════════════════════════════════════════════════════"
else
    echo "════════════════════════════════════════════════════════════"
    echo "  EXECUTION COMPLETE — see 'broadcast_tx' above for the hash"
    echo "════════════════════════════════════════════════════════════"
fi
