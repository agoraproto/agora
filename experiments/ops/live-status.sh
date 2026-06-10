#!/usr/bin/env bash
# Sprint 51 -- Agora on-chain live-status snapshot.
#
# Read-only. Pulls the current state of all four on-chain entities into
# a single human-readable table:
#   * V1 escrow (legacy, 1.21 USDC stuck in 3 Submitted jobs)
#   * V2 escrow (live, Timelock-owned post-Sprint-45)
#   * Timelock controller (queued operations, ready/done status)
#   * 2-of-2 Safe (threshold, nonce)
#
# Run from PowerShell:
#   Get-Content C:\Users\WAVO\Desktop\Projekte\agor\sprint51-live-status.sh -Raw | ssh root@188.245.39.250 bash
#
# Suggested daily habit: run before broadcasting any admin op to confirm
# the world is in the state you expect.

set -uo pipefail   # no -e: keep collecting state even if one call errors

CAST=/root/.foundry/bin/cast
RPC=https://sepolia.base.org

V1=0xCE783B527C83c4fFFF3D3565c0F3C3204be02B76
V2=0x0e8E6A760c76cA92c5C5dA06d293E33f1B5fbAEc
TIMELOCK=0xeE37C2289052038376aD5DAb7cAAbe765655F024
SAFE=0x8Ec63Fe30DAb84308B5009b8D91d9E4dEB5a61FC
USDC=0x036CbD53842c5426634e7929541eC2318f3dCF7e

# Helper: cast call + strip the human-readable suffix
call() {
    $CAST call "$@" --rpc-url $RPC 2>/dev/null | awk '{print $1}'
}

# Format micro-USDC as USDC with 6 decimals
fmt_usdc() {
    local micros=$1
    if [ -z "$micros" ] || [ "$micros" = "0" ]; then
        echo "0.000000"
        return
    fi
    # micros / 1_000_000 with 6 decimals; bc is gentle on tiny numbers
    echo "scale=6; $micros / 1000000" | bc
}

# Format unix timestamp as ISO
fmt_ts() {
    local ts=$1
    if [ -z "$ts" ] || [ "$ts" = "0" ]; then
        echo "(never)"
        return
    fi
    date -u -d "@$ts" +'%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo "ts=$ts"
}

NOW=$(date -u +%s)

echo "════════════════════════════════════════════════════════════"
echo "  Agora live-status snapshot   $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo "  Chain: Base Sepolia (84532)"
echo "════════════════════════════════════════════════════════════"

# ── V1 escrow (legacy) ──────────────────────────────────────────
echo ""
echo "── V1 escrow (legacy) ────────────────────────────────────────"
V1_BAL=$(call $USDC "balanceOf(address)(uint256)" $V1)
echo "  Address:    $V1"
echo "  USDC held:  $V1_BAL micro-USDC ($(fmt_usdc $V1_BAL) USDC)"
echo "  Expected:   1.210000 USDC stuck in 3 Submitted-status jobs (Sprint 42 done 2026-06-10)"

# ── V2 escrow ───────────────────────────────────────────────────
echo ""
echo "── V2 escrow (live) ─────────────────────────────────────────"
V2_BAL=$(call $USDC "balanceOf(address)(uint256)" $V2)
V2_OWNER=$(call $V2 "owner()(address)")
V2_PENDING=$(call $V2 "pendingOwner()(address)" 2>/dev/null || echo "0x0000000000000000000000000000000000000000")
V2_PAUSED=$(call $V2 "paused()(bool)")
V2_FEE_BPS=$(call $V2 "feeBps()(uint16)")
V2_MIN_FEE=$(call $V2 "minFee()(uint256)")
V2_MAX_FEE=$(call $V2 "maxFee()(uint256)")
V2_INS_SHARE=$(call $V2 "insuranceShareBps()(uint16)")
V2_TOTAL_ESC=$(call $V2 "totalEscrowed()(uint256)")
echo "  Address:        $V2"
echo "  Owner:          $V2_OWNER"
if [ "${V2_OWNER,,}" = "${TIMELOCK,,}" ]; then
    echo "                  -> Timelock (Sprint 45 Phase 2b)"
elif [ "${V2_OWNER,,}" = "${SAFE,,}" ]; then
    echo "                  -> Safe (pre-Phase-2b)"
else
    echo "                  -> UNKNOWN -- investigate"
fi
echo "  pendingOwner:   $V2_PENDING"
echo "  USDC balance:   $V2_BAL micro-USDC ($(fmt_usdc $V2_BAL) USDC)"
echo "  totalEscrowed:  $V2_TOTAL_ESC micro-USDC ($(fmt_usdc $V2_TOTAL_ESC) USDC)"
if [ -n "$V2_BAL" ] && [ -n "$V2_TOTAL_ESC" ] && [ "$V2_BAL" != "$V2_TOTAL_ESC" ]; then
    DELTA=$((V2_BAL - V2_TOTAL_ESC))
    echo "                  WARNING: balance != totalEscrowed (delta=$DELTA micro-USDC)"
fi
echo "  Paused:         $V2_PAUSED"
echo "  Fee config:     feeBps=$V2_FEE_BPS, minFee=$(fmt_usdc $V2_MIN_FEE), maxFee=$(fmt_usdc $V2_MAX_FEE), insShareBps=$V2_INS_SHARE"

# ── Timelock ────────────────────────────────────────────────────
echo ""
echo "── TimelockController ───────────────────────────────────────"
TL_MIN_DELAY=$(call $TIMELOCK "getMinDelay()(uint256)")
TL_PROPOSER_ROLE=$(call $TIMELOCK "PROPOSER_ROLE()(bytes32)")
TL_EXECUTOR_ROLE=$(call $TIMELOCK "EXECUTOR_ROLE()(bytes32)")
TL_ADMIN_ROLE=$(call $TIMELOCK "DEFAULT_ADMIN_ROLE()(bytes32)")
SAFE_HAS_PROP=$(call $TIMELOCK "hasRole(bytes32,address)(bool)" $TL_PROPOSER_ROLE $SAFE)
SAFE_HAS_EXEC=$(call $TIMELOCK "hasRole(bytes32,address)(bool)" $TL_EXECUTOR_ROLE $SAFE)
SAFE_HAS_ADMIN=$(call $TIMELOCK "hasRole(bytes32,address)(bool)" $TL_ADMIN_ROLE $SAFE)
echo "  Address:                  $TIMELOCK"
echo "  minDelay:                 $TL_MIN_DELAY seconds (= $((TL_MIN_DELAY / 3600))h)"
echo "  Safe has PROPOSER_ROLE:   $SAFE_HAS_PROP  (expected true)"
echo "  Safe has EXECUTOR_ROLE:   $SAFE_HAS_EXEC  (expected true)"
echo "  Safe has ADMIN_ROLE:      $SAFE_HAS_ADMIN  (expected false)"

# Known queued ops (from prior sprints)
echo ""
echo "  Known queued ops:"
declare -A KNOWN_OPS=(
    ["sprint45-phase2a-acceptOwnership"]="0xba84103fbe4454345191167038b813c9036917049dac1f8ae87278a487ab4471"
    ["sprint50-rolling-pause-2026-06-10"]="0x57fcd13dde5df8abfcb48c71b1a347cdeb31e613ff2b36bf394771394796a0e3"
)
for name in "${!KNOWN_OPS[@]}"; do
    OP=${KNOWN_OPS[$name]}
    OP_PENDING=$(call $TIMELOCK "isOperationPending(bytes32)(bool)" $OP)
    OP_READY=$(call $TIMELOCK "isOperationReady(bytes32)(bool)" $OP)
    OP_DONE=$(call $TIMELOCK "isOperationDone(bytes32)(bool)" $OP)
    OP_TS=$(call $TIMELOCK "getTimestamp(bytes32)(uint256)" $OP)
    OP_ETA=$(fmt_ts $OP_TS)
    if [ "$OP_DONE" = "true" ]; then
        STATUS="done"
    elif [ "$OP_READY" = "true" ]; then
        STATUS="READY (executable now)"
    elif [ "$OP_PENDING" = "true" ]; then
        DELTA=$((OP_TS - NOW))
        if [ "$DELTA" -gt 0 ]; then
            STATUS="pending ($((DELTA / 3600))h $((DELTA % 3600 / 60))m to ready)"
        else
            STATUS="pending (overdue by $(( -DELTA / 60 ))m)"
        fi
    else
        STATUS="unknown / not scheduled"
    fi
    printf "    %-45s %s\n" "$name" "$STATUS"
    printf "    %-45s op=%s earliest=%s\n" "" "$OP" "$OP_ETA"
done

# ── Safe ────────────────────────────────────────────────────────
echo ""
echo "── 2-of-2 Safe ──────────────────────────────────────────────"
SAFE_NONCE=$(call $SAFE "nonce()(uint256)")
SAFE_THRESHOLD=$(call $SAFE "getThreshold()(uint256)")
SAFE_BAL=$($CAST balance $SAFE --rpc-url $RPC 2>/dev/null | awk '{print $1}')
echo "  Address:    $SAFE"
echo "  Threshold:  $SAFE_THRESHOLD"
echo "  Nonce:      $SAFE_NONCE  (last broadcast = nonce $((SAFE_NONCE - 1)))"
echo "  ETH:        $SAFE_BAL wei (Safe holds no native ETH by design)"

# ── DB sanity (optional) ──────────────────────────────────────
echo ""
echo "── DB job-status counts ─────────────────────────────────────"
if command -v psql >/dev/null 2>&1; then
    sudo -u postgres psql agora -tAc "
        SELECT
            COALESCE(escrow_contract_address, '(null)') AS escrow,
            settlement_mode,
            status,
            COUNT(*) AS n
        FROM jobs
        WHERE settlement_mode IN ('onchain', 'offchain')
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    " | awk -F'|' '{ printf "  %-44s %-9s %-12s %s\n", $1, $2, $3, $4 }'
else
    echo "  (psql not available)"
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  End of snapshot."
echo "════════════════════════════════════════════════════════════"
