# RUNBOOK — The permanent-pause queue

**Sprint 45 / Option B mitigation.** Defeats the 24h pause delay by
keeping a `pause()` proposal always within < 24h of executable.

## The problem (and why this exists)

Under Option B the Timelock owns V2, including `pause()`. If we discover
a critical exploit in V2 at hour 0, the soonest we can pause is hour 24.
That's not acceptable for an emergency stop.

## The mitigation: a rolling pre-queued pause

Always have **one** `pause()` proposal scheduled on the Timelock. Its
24h delay rolls forward continuously — when the current one has < 1h
left until executable, schedule a fresh one and (optionally) cancel the
old one. This way:

- Hour 0: discover exploit
- Hour 0: execute the already-queued pause (current proposal is, by
  invariant, within 24h of executable)

The cost is one scheduled proposal sitting in the Timelock at all times.
The Safe must keep refreshing it.

## Implementation: schedule a new pause proposal every 23h

The unique identity of a Timelock proposal is its `(target, value,
calldata, predecessor, salt)` hash. To keep proposals from colliding
(or being detected as duplicate), each refresh uses a different `salt`.

Variant 1 (recommended for cleanliness): cancel the old proposal once
the new one is queued. There's only ever exactly one pause queued.

Variant 2 (recommended for safety): leave the old proposal active until
it actually expires from the queue. There may be 1-2 pause proposals
active at any moment. This avoids any window where there's no queued
pause.

Either way is fine for Sepolia. Use Variant 2 for Mainnet operations.

### Initial queue (one-time, after ownership flip lands)

```bash
$CAST=/root/.foundry/bin/cast
RPC=https://sepolia.base.org
TL=0x<TIMELOCK_ADDR>
V2=0x0e8E6A760c76cA92c5C5dA06d293E33f1B5fbAEc

PAUSE_CALL=$($CAST calldata "pause()")
# = 0x8456cb59

SALT=$($CAST keccak "agora-rolling-pause-$(date -u +%Y%m%d%H)")
SCHEDULE_CALL=$($CAST calldata "schedule(address,uint256,bytes,bytes32,bytes32,uint256)" \
  $V2 0 $PAUSE_CALL \
  0x0000000000000000000000000000000000000000000000000000000000000000 \
  $SALT 86400)
```

Then via Safe (`safe-admin-op.sh` with TARGET=$TL, CALLDATA=$SCHEDULE_CALL):
broadcast. Record the OP_ID and SALT — needed for execution / cancel.

```bash
OP_ID=$($CAST call $TL "hashOperation(address,uint256,bytes,bytes32,bytes32)(bytes32)" \
  $V2 0 $PAUSE_CALL 0x00...00 $SALT --rpc-url $RPC)
echo "Pause proposal pending: $OP_ID (salt=$SALT)"
```

### Refresh (run every 23h via systemd timer on agora-1)

Conceptually:

```bash
# Build the next pause proposal with a fresh salt
NEXT_SALT=$($CAST keccak "agora-rolling-pause-$(date -u +%Y%m%d%H)")
NEXT_SCHEDULE=$($CAST calldata "schedule(address,uint256,bytes,bytes32,bytes32,uint256)" \
  $V2 0 $PAUSE_CALL 0x00...00 $NEXT_SALT 86400)

# Have the Safe sign + broadcast the schedule
# (this requires the Safe; the timer can prepare the calldata but the
# actual broadcast needs human cosigners or an agreed automation)
```

**Operational reality:** because every schedule needs both Safe
cosigners to sign, full automation requires either (a) one cosigner
hot-key + one cold-key with semi-automated approval, or (b) accepting
that the rolling-pause refresh is a manual on-call task.

For Sepolia: we'll do it manually as part of the "twice a week, eyeball
the state" routine. The 24h window is forgiving enough that one missed
refresh just means: for the next ~few hours we don't have a queued
pause, no live damage unless an exploit drops in that exact gap.

For Mainnet: this should be properly automated or replaced by V2.1's
direct pauser-role pattern.

## Execution in emergency

When the exploit fires:

```bash
EXECUTE_CALL=$($CAST calldata "execute(address,uint256,bytes,bytes32,bytes32)" \
  $V2 0 $PAUSE_CALL 0x00...00 $SALT)
```

Safe broadcasts via `safe-admin-op.sh`. V2.paused() == true immediately.

Anyone with EXECUTOR_ROLE can execute — that's only the Safe at the
moment, but if speed matters, consider widening EXECUTOR_ROLE to a
hot key (or to `address(0)` for trustless execution after delay) in a
future operational change.

## Failure modes

| Mode | Effect | Mitigation |
|---|---|---|
| Refresh missed for >24h | No queued pause ready | Acceptable risk window. Schedule a new one ASAP. |
| Refresh succeeded but Safe loses both cosigner keys | Can't execute even the queued pause | Separate problem (Safe recovery); the queued pause won't save you. |
| Exploit fires within the salt-rotation seam | Brief window of no-queued-pause | Variant 2 (overlap) eliminates this. |

