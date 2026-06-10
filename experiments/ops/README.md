# Agora ops scripts

Read-only operational tooling. Run from a local shell that has SSH access
to `agora-1`.

## live-status.sh

Snapshot of the current on-chain state across V1 escrow, V2 escrow,
TimelockController, 2-of-2 Safe, plus a DB job-status count summary.

```powershell
Get-Content C:\Users\WAVO\Desktop\Projekte\agor\experiments\ops\live-status.sh -Raw | ssh root@188.245.39.250 bash
```

Useful before broadcasting any admin op (confirm the world is in the
state you expect), and as a canonical reference for external reviewers
who want to see the live values without trusting the docs.

Tracks the queued Timelock operations by op-id (hardcoded constants at
the top of the script). When new operations are queued, add their op-id
to the `KNOWN_OPS` table near line 100.

## What this is NOT

Read-only. Never writes state. Never broadcasts. Never moves money.
Safe to run from cron if you want a daily snapshot (no risk).
