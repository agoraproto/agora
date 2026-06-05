# RUNBOOK — Flip V2 owner from Safe to Timelock

**Sprint 45 / Option B.** Two-phase, total elapsed time ≥ 24h.

## State before

- `AgoraEscrowV2.owner()` = `0x8Ec63Fe30DAb84308B5009b8D91d9E4dEB5a61FC` (the Safe, per Sprint 37c)
- `TimelockController` (from `RUNBOOK_DEPLOY.md`) is deployed and verified

## State after

- `AgoraEscrowV2.owner()` = `0x<TIMELOCK_ADDR>` (the Timelock)
- Safe loses direct admin power; Safe is now PROPOSER on the Timelock

## Why this is two phases

`AgoraEscrowV2` is `Ownable2Step`:

1. The current owner calls `transferOwnership(newOwner)` → sets `pendingOwner`
2. The pending owner calls `acceptOwnership()` → finalises the transfer

Since the **Timelock** will be the new owner, step (2) must originate
from the Timelock itself. That means: Safe schedules `acceptOwnership()`
on the Timelock, waits 24h, executes. Total elapsed time = 24h + whatever
gap between steps.

---

## Phase 1 — Safe calls V2.transferOwnership(timelock)

Edit `safe-admin-op.sh` (committed at repo root, see `experiments/safe-multisig/admin-op-template.sh`):

```bash
DRY_RUN=1                                            # ALWAYS preview first
TARGET=0x0e8E6A760c76cA92c5C5dA06d293E33f1B5fbAEc    # V2
TARGET_VALUE=0
CALLDATA=$($CAST calldata "transferOwnership(address)" 0x<TIMELOCK_ADDR>)
```

Preview (no broadcast):
```powershell
Get-Content C:\Users\WAVO\Desktop\Projekte\agor\safe-admin-op.sh -Raw `
  | ssh root@188.245.39.250 "DRY_RUN=1 bash"
```

Expect output to show `transferOwnership(<TIMELOCK_ADDR>)` calldata,
SafeTxHash, both cosigner signatures, simulation success.

Broadcast:
```powershell
Get-Content C:\Users\WAVO\Desktop\Projekte\agor\safe-admin-op.sh -Raw `
  | ssh root@188.245.39.250 "DRY_RUN=0 bash"
```

Verify on-chain:
```bash
$CAST call $V2 "pendingOwner()(address)" --rpc-url $RPC
# Expect: 0x<TIMELOCK_ADDR>
$CAST call $V2 "owner()(address)" --rpc-url $RPC
# Expect: still 0x8Ec6... (Safe) -- transfer is not finalised yet
```

**Checkpoint reached:** Safe is still owner, Timelock is pendingOwner.

---

## Phase 2 — Schedule acceptOwnership() via Timelock, wait 24h, execute

Phase 2a — Safe schedules the acceptOwnership call:

```bash
# Build the inner calldata: V2.acceptOwnership()
ACCEPT_CALL=$($CAST calldata "acceptOwnership()")
# = 0x79ba5097

# Build the outer Timelock.schedule(target, value, payload, predecessor, salt, delay) calldata
SALT=$($CAST keccak "agora-timelock-accept-v2-ownership")
SCHEDULE_CALL=$($CAST calldata "schedule(address,uint256,bytes,bytes32,bytes32,uint256)" \
  $V2 0 $ACCEPT_CALL 0x0000000000000000000000000000000000000000000000000000000000000000 \
  $SALT 86400)
```

Then edit `safe-admin-op.sh` to call the Timelock:
```bash
TARGET=0x<TIMELOCK_ADDR>
TARGET_VALUE=0
CALLDATA=$SCHEDULE_CALL
```

Preview, then broadcast. After broadcast verify:
```bash
$CAST call $TL "isOperationPending(bytes32)(bool)" \
  $($CAST call $TL "hashOperation(address,uint256,bytes,bytes32,bytes32)(bytes32)" \
       $V2 0 $ACCEPT_CALL 0x00...00 $SALT) \
  --rpc-url $RPC
# Expect: true
```

**Checkpoint reached:** `acceptOwnership()` is queued, executable in 24h.

**Wait at least 24h** before phase 2b. During the wait window any
observer can see the pending proposal via Timelock events:

```bash
$CAST logs --from-block $((LATEST - 200)) \
  --address $TL \
  "CallScheduled(bytes32,uint256,address,uint256,bytes,bytes32,uint256)" \
  --rpc-url $RPC
```

---

Phase 2b — after the 24h delay, Safe (or anyone with EXECUTOR_ROLE)
executes:

```bash
EXECUTE_CALL=$($CAST calldata "execute(address,uint256,bytes,bytes32,bytes32)" \
  $V2 0 $ACCEPT_CALL 0x0000000000000000000000000000000000000000000000000000000000000000 $SALT)
```

Edit `safe-admin-op.sh` again with TARGET=$TL, CALLDATA=$EXECUTE_CALL.
Broadcast.

Verify the flip:
```bash
$CAST call $V2 "owner()(address)" --rpc-url $RPC
# Expect: 0x<TIMELOCK_ADDR>
$CAST call $V2 "pendingOwner()(address)" --rpc-url $RPC
# Expect: 0x0000000000000000000000000000000000000000
```

**Done.** V2 is now Timelock-owned. Update:

- `contracts/SECURITY_REVIEW_V2.md` §1: "Owner: Timelock at 0x<TIMELOCK_ADDR>"
- Issue #1 comment: post a summary "V2 owner flip complete, Timelock = ...".
- Queue the permanent pause per `RUNBOOK_PERMANENT_PAUSE_QUEUE.md`.

## Recovery — what if Phase 2 stalls?

If Phase 2 scheduling fails: nothing happens. V2 is still Safe-owned
(Phase 1 only set pendingOwner; pendingOwner can be overwritten with a
fresh `transferOwnership(otherAddr)` from the Safe).

If Phase 2 schedules but Safe wants to abort during the 24h window:
```bash
CANCEL_CALL=$($CAST calldata "cancel(bytes32)" $OP_ID)
# Safe broadcasts via safe-admin-op.sh with TARGET=$TL, CALLDATA=$CANCEL_CALL
```

CANCELLER_ROLE was granted to Safe automatically (it comes with PROPOSER_ROLE
in the OZ TimelockController constructor).

If Phase 2 executes and we discover it was a mistake: V2 is now
Timelock-owned, so the recovery path is `transferOwnership` back to
Safe via the Timelock — that itself requires a 24h scheduled proposal.
There is no instant rollback once Phase 2 lands. This is by design.
