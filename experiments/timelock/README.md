# Timelock — OZ TimelockController, 24h delay, Safe-controlled

**Sprint 45, Option B** of `contracts/TIMELOCK_DESIGN.md`.

The deployed-on-Sepolia OpenZeppelin `TimelockController` is the new
`Ownable2Step` owner of `AgoraEscrowV2`. The 2-of-2 Safe is the
sole **proposer / canceller / executor**. Every admin call now follows:

```
   Safe.execTransaction()
        └─> Timelock.schedule(...)       // queue, 24h delay starts
        └─> [24h wait, public visibility on-chain]
        └─> Timelock.execute(...)        // actually runs on V2
```

## Files in this folder

- `RUNBOOK_OWNERSHIP_FLIP.md` — one-time flip of V2 owner from Safe
  directly to the Timelock (after Sprint 37c had Safe accept ownership).
- `RUNBOOK_PERMANENT_PAUSE_QUEUE.md` — the "always-ready pause"
  mitigation for Option B's pause delay (TIMELOCK_DESIGN.md §4).
- `RUNBOOK_DEPLOY.md` — the actual deploy commands.

## Why Option B (rather than V2.1 with separate pauser role)

Sepolia / testnet practice phase. The redeploy cost of V2.1 outweighs
the operational cost of a queued pause until we reach Mainnet. Option B
gives us live experience operating a Timelock-fronted V2 before
committing to the V2.1 pause-role contract change.

For Mainnet the recommendation in TIMELOCK_DESIGN.md stays: do not
deploy to Mainnet without V2.1's separate pauser role.

## Known operational costs of Option B

| Cost | Mitigation |
|---|---|
| `pause()` waits 24h | `RUNBOOK_PERMANENT_PAUSE_QUEUE.md` — always have a queued pause within < 24h of executable |
| Fee parameter change waits 24h | Acceptable; revenue tuning is not time-critical |
| Dispute resolution waits 24h | **Not acceptable** — `resolveDispute` should stay direct; see TIMELOCK_DESIGN.md §5. V2 currently routes `resolveDispute` through `onlyOwner` so it WILL go through the Timelock once ownership flips. This is a known regression for Sprint 45 and tracked separately. |

The dispute regression is real: post-Sprint 45 the Safe can no longer
resolve disputes within 24h. Until V2.1 carves `resolveDispute` out,
the Safe should keep an `unpaused, resolveDispute(...)` proposal
pre-queued as soon as a dispute escalates.
