# experiments/v1-cleanup

Reclaim USDC stuck in the V1 escrow contract after the V1 → V2 flip
(Sprint 35h). V1's `refund(jobId)` is permissionless once the on-chain
deadline has elapsed, so we can rescue these without owner-key
involvement.

As of 2026-06-05 the V1 contract
`0xCE783B527C83c4fFFF3D3565c0F3C3204be02B76` holds ~10.62 USDC across
the live `Funded`/`Disputed` jobs that never got settled before the
V2 flip.

## How to run

### Dry run (default, safe)

```powershell
Get-Content C:\Users\WAVO\Desktop\Projekte\agor\experiments\v1-cleanup\cleanup.sh -Raw | ssh root@188.245.39.250 bash
```

Reports what *would* be refunded across four buckets:
- **Refundable NOW** — Funded/Disputed with deadline elapsed; permissionless refund works
- **Refundable LATER** — Funded/Disputed with deadline still in the future
- **Terminal** — already Approved or Refunded; nothing to do
- **Not found** — chain returned None (orphaned DB row pointing at a
  jobId that V1 never knew, e.g. test data; ignored)

No state changes, no broadcasts.

### Execute (broadcasts)

```powershell
Get-Content C:\Users\WAVO\Desktop\Projekte\agor\experiments\v1-cleanup\cleanup.sh -Raw | ssh root@188.245.39.250 "EXECUTE=1 bash"
```

Broadcasts one `V1.refund(jobId)` per refundable-now job using the
deployer key at `/opt/agora/experiments/swarm/.deployer-key` for gas.
Updates the corresponding `jobs` row in the DB to `status=refunded`
with the tx hash.

The deployer wallet only pays gas (~70k per tx × N jobs). USDC goes
back to the original payers, not to the deployer.

## Why permissionless refund works

V1's `refund(uint256 jobId)`:

```solidity
function refund(uint256 jobId) external {
    Job storage j = jobs[jobId];
    if (j.status != JobStatus.Funded && j.status != JobStatus.Disputed)
        revert InvalidStatus();
    bool deadlineExpired = block.timestamp > j.deadline;
    if (!deadlineExpired && msg.sender != owner) revert Unauthorized();
    j.status = JobStatus.Refunded;
    _transfer(j.payer, j.amount);
    emit JobRefunded(jobId);
}
```

After deadline, `msg.sender != owner` is OK because `deadlineExpired`
short-circuits the check. Anyone can call it; the USDC goes to the
original payer (`j.payer`). The deployer in this script is only the
relayer — they pay gas but don't receive any USDC.

## Risk surface

- **No risk to non-payer USDC.** Refund sends to `j.payer`, not to the
  caller. Even a malicious script invocation can't divert funds.
- **Idempotent at the contract level.** Second call on the same jobId
  reverts (`InvalidStatus`) because state is now Refunded.
- **DB update is best-effort.** If the chain refund succeeded but the
  DB update failed, the next dry run will show the job as Terminal
  (the chain status will be Refunded), so subsequent runs are still safe.
- **Submitted jobs are intentionally NOT refunded.** V1 doesn't allow
  refund from Submitted state without owner action. Those need a manual
  dispute → owner-resolve flow if any payer wants their money back.

## Expected before/after

```
V1 USDC before:  10620000 micro-USDC = 10.620000 USDC
V1 USDC after:   ~0 micro-USDC = ~0 USDC (anything Funded/elapsed clears)
```

The actual delta depends on how many of the ~535 V1-legacy DB jobs were
truly Funded with elapsed deadline (vs. Approved-and-completed,
Submitted-but-never-approved, etc.). The dry run output tells you the
exact set before you commit.
