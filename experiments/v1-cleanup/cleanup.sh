#!/usr/bin/env bash
# Sprint 42 — V1 legacy USDC cleanup
#
# 10.62 USDC are stuck in the V1 escrow contract from jobs that were
# in-flight when the V1 -> V2 flip happened (Sprint 35h). V1's refund()
# is permissionless once the on-chain deadline has elapsed, so we can
# rescue these without owner-key involvement.
#
# DEFAULT MODE: dry-run. Reports what WOULD be refunded.
# Set EXECUTE=1 to actually broadcast the refund transactions.
#
# Run from a Windows PowerShell:
#   Get-Content C:\Users\WAVO\Desktop\Projekte\agor\sprint42-v1-cleanup.sh -Raw | ssh root@188.245.39.250 bash
# or to actually execute:
#   Get-Content ...\sprint42-v1-cleanup.sh -Raw | ssh root@188.245.39.250 "EXECUTE=1 bash"

V1=0xCE783B527C83c4fFFF3D3565c0F3C3204be02B76
USDC=0x036CbD53842c5426634e7929541eC2318f3dCF7e
RPC=https://sepolia.base.org
CAST=/root/.foundry/bin/cast
DEPLOYER_KEY_FILE=/opt/agora/experiments/swarm/.deployer-key

EXECUTE=${EXECUTE:-0}

echo "============================================================"
echo "  Sprint 42 -- V1 legacy USDC cleanup  $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo "  Mode: $([ "$EXECUTE" = "1" ] && echo "EXECUTE (broadcasting refund txs)" || echo "DRY RUN (no broadcast)")"
echo "============================================================"

# Pre-flight: how much USDC is actually stuck?
V1_USDC=$($CAST call $USDC "balanceOf(address)(uint256)" $V1 --rpc-url $RPC)
echo ""
echo "=== Pre-flight ==="
echo "  V1 contract:    $V1"
echo "  V1 USDC held:   $V1_USDC micro-USDC ($(echo "scale=6; $V1_USDC / 1000000" | bc) USDC)"
NOW=$(date +%s)
echo "  block.timestamp: $NOW (approx)"

# Pull V1-legacy jobs from DB. These are jobs marked V1 in escrow_contract_address
# (Sprint 36g-fix backfilled this for all pre-Sprint-37 onchain jobs).
echo ""
echo "=== [1/3] Pull V1 candidate jobs from DB ==="
V1_JOBS=$(sudo -u postgres psql agora -tAc "
    SELECT onchain_job_id::text
    FROM jobs
    WHERE settlement_mode = 'onchain'
      AND escrow_contract_address = '$V1'
      AND status IN ('offered','submitted','disputed')
      AND onchain_job_id IS NOT NULL
    ORDER BY created_at ASC
")
N_DB=$(echo "$V1_JOBS" | grep -c .)
echo "  DB has $N_DB V1-legacy onchain jobs in non-terminal status"

if [ -z "$V1_JOBS" ]; then
    echo "  Nothing to do at the DB layer. (USDC may still be stuck if V1 had"
    echo "  jobs we never created via our API.)"
    exit 0
fi

# For each candidate: read on-chain state. Categorise into refundable now,
# refundable later, terminal, owner-only.
echo ""
echo "=== [2/3] Categorise each candidate by on-chain state ==="
declare -a REFUND_NOW
declare -a REFUND_LATER
declare -a TERMINAL
declare -a OWNER_ONLY
declare -a NOT_FOUND

while IFS= read -r jid; do
    [ -z "$jid" ] && continue
    # V1.jobs(jobId) returns (payer, payee, amount, taskHash, resultHash, deadline, status)
    out=$($CAST call $V1 "jobs(uint256)(address,address,uint256,bytes32,bytes32,uint64,uint8)" \
        "$jid" --rpc-url $RPC 2>&1)
    if echo "$out" | grep -qi "revert\|error"; then
        NOT_FOUND+=("$jid")
        continue
    fi
    # Parse tuple output -- cast returns one value per line
    payer=$(echo "$out"   | sed -n '1p')
    amount=$(echo "$out"  | sed -n '3p' | awk '{print $1}')
    deadline=$(echo "$out" | sed -n '6p')
    status=$(echo "$out"  | sed -n '7p')

    # V1 status enum: 0=None, 1=Funded, 2=Submitted, 3=Approved, 4=Disputed, 5=Refunded
    case "$status" in
        3|5)
            TERMINAL+=("$jid status=$status")
            ;;
        0)
            NOT_FOUND+=("$jid (chain returned None)")
            ;;
        1|4)
            # Funded or Disputed -- refundable if deadline elapsed (permissionless)
            if [ "$NOW" -gt "$deadline" ]; then
                # V1 refund only valid on Funded or Disputed
                REFUND_NOW+=("$jid amount=$amount status=$status deadline=$deadline")
            else
                ELAPSE_IN=$((deadline - NOW))
                REFUND_LATER+=("$jid amount=$amount status=$status elapse_in=${ELAPSE_IN}s")
            fi
            ;;
        2)
            # Submitted: V1 refund() is NOT permitted in this state -- the
            # payer must approve, or both parties dispute. Out of scope for
            # this cleanup script.
            TERMINAL+=("$jid (Submitted -- not refundable, payer must approve or dispute)")
            ;;
        *)
            OWNER_ONLY+=("$jid unknown_status=$status")
            ;;
    esac
done <<< "$V1_JOBS"

echo "  Refundable NOW (Funded/Disputed + deadline elapsed):  ${#REFUND_NOW[@]}"
echo "  Refundable LATER (deadline not yet elapsed):          ${#REFUND_LATER[@]}"
echo "  Terminal (already Approved/Refunded, or Submitted):   ${#TERMINAL[@]}"
echo "  Owner-only / unusual status:                          ${#OWNER_ONLY[@]}"
echo "  Not found on chain (orphaned in DB):                  ${#NOT_FOUND[@]}"

if [ "${#REFUND_NOW[@]}" -gt 0 ]; then
    echo ""
    echo "  --- Refundable NOW (first 20):"
    for entry in "${REFUND_NOW[@]:0:20}"; do
        echo "    $entry"
    done
fi
if [ "${#REFUND_LATER[@]}" -gt 0 ]; then
    echo ""
    echo "  --- Refundable LATER (first 5):"
    for entry in "${REFUND_LATER[@]:0:5}"; do
        echo "    $entry"
    done
fi
if [ "${#NOT_FOUND[@]}" -gt 0 ]; then
    echo ""
    echo "  --- Not found on V1 contract (first 5):"
    for entry in "${NOT_FOUND[@]:0:5}"; do
        echo "    $entry"
    done
fi

# Phase 3: execute refunds if EXECUTE=1
echo ""
echo "=== [3/3] Broadcast phase ==="

if [ "$EXECUTE" != "1" ]; then
    echo "  DRY RUN -- no broadcast. To actually refund, re-run with EXECUTE=1."
    echo ""
    if [ "${#REFUND_NOW[@]}" -gt 0 ]; then
        sum_refund=0
        for entry in "${REFUND_NOW[@]}"; do
            amt=$(echo "$entry" | sed -n 's/.*amount=\([0-9]*\).*/\1/p')
            sum_refund=$((sum_refund + amt))
        done
        echo "  Would refund: $sum_refund micro-USDC = $(echo "scale=6; $sum_refund / 1000000" | bc) USDC across ${#REFUND_NOW[@]} jobs"
        echo "  Estimated gas: ~70 000 gas per refund x ${#REFUND_NOW[@]} = ~$((70000 * ${#REFUND_NOW[@]})) gas total"
    fi
    exit 0
fi

# Real execution path
if [ "${#REFUND_NOW[@]}" -eq 0 ]; then
    echo "  No refundable-now jobs. Nothing to broadcast."
    exit 0
fi

DEPLOYER_KEY=$(cat "$DEPLOYER_KEY_FILE" | tr -d '[:space:]')
[[ "$DEPLOYER_KEY" != 0x* ]] && DEPLOYER_KEY="0x$DEPLOYER_KEY"
DEPLOYER_ADDR=$($CAST wallet address --private-key "$DEPLOYER_KEY")
echo "  Relayer (pays gas): $DEPLOYER_ADDR"
ETH_BAL=$($CAST balance $DEPLOYER_ADDR --rpc-url $RPC)
echo "  Deployer ETH:       $ETH_BAL wei"

SUCCESS=0
FAILED=0
for entry in "${REFUND_NOW[@]}"; do
    jid=$(echo "$entry" | awk '{print $1}')
    echo ""
    echo "  Refunding V1 jobId=$jid..."
    TX=$($CAST send \
        --rpc-url $RPC \
        --private-key "$DEPLOYER_KEY" \
        --gas-limit 100000 \
        $V1 \
        "refund(uint256)" \
        "$jid" \
        --json 2>&1 | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    print(d.get('transactionHash', 'unknown'))
except Exception as e:
    print(f'PARSE_ERR: {e}')
")
    if [[ "$TX" == 0x* ]]; then
        echo "    tx: $TX"
        SUCCESS=$((SUCCESS + 1))
        # Optional: update DB row to status=refunded
        sudo -u postgres psql agora -tAc "
            UPDATE jobs SET status='refunded', release_tx_hash='$TX'
            WHERE onchain_job_id::text = '$jid'
              AND escrow_contract_address = '$V1'
        " >/dev/null
    else
        echo "    FAIL: $TX"
        FAILED=$((FAILED + 1))
    fi
    # Small sleep to be gentle on the public RPC
    sleep 0.5
done

echo ""
echo "============================================================"
echo "  Refund batch done."
echo "  Success: $SUCCESS / ${#REFUND_NOW[@]}"
echo "  Failed:  $FAILED"
echo ""
V1_USDC_AFTER=$($CAST call $USDC "balanceOf(address)(uint256)" $V1 --rpc-url $RPC)
echo "  V1 USDC after:  $V1_USDC_AFTER micro-USDC ($(echo "scale=6; $V1_USDC_AFTER / 1000000" | bc) USDC)"
echo "  V1 USDC before: $V1_USDC micro-USDC"
echo "  Delta:          $(($V1_USDC - $V1_USDC_AFTER)) micro-USDC released"
echo "============================================================"
