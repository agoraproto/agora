# experiments/v2-smoke

Generator for `apps/backend/docs/V2_LIVE_STATE.md` — a mechanically
produced single-page audit of the V2 escrow contract's live state on
Base Sepolia plus the backend / DB / watcher state that depends on it.

Re-run whenever you want a fresh snapshot:

```powershell
$out = Get-Content C:\Users\WAVO\Desktop\Projekte\agor\experiments\v2-smoke\regenerate.sh -Raw | ssh root@188.245.39.250 bash
[System.IO.File]::WriteAllText(
    "C:\Users\WAVO\Desktop\Projekte\agor\apps\backend\docs\V2_LIVE_STATE.md",
    $out,
    [System.Text.UTF8Encoding]::new($false)
)
```

(Linux / macOS / WSL equivalent:)

```bash
ssh root@agora-1 bash < experiments/v2-smoke/regenerate.sh > apps/backend/docs/V2_LIVE_STATE.md
```

The script is read-only — it does not modify anything on the server or
on-chain. It only calls `cast call`, reads the backend `.env`, queries
the database, and tails recent logs.

## What it checks

1. **Canonical addresses** — V2 / Safe / USDC / Deployer / Cosigners.
2. **V2 on-chain state** — owner, pendingOwner, paused, fee params,
   nextJobId, totalEscrowed.
3. **Safe state** — threshold, owners, nonce.
4. **V2 ABI probes** — `previewFee` works, `refundExpired` exists,
   `computeFee` correctly absent (V1 legacy fn).
5. **Backend config** — `.env` reads of `ESCROW_CONTRACT_ADDRESS` and
   `ESCROW_ABI_VERSION`, alembic head, `/v1/state` HTTP.
6. **Chain-watcher filter** — DB counts of V1-legacy vs V2 vs NULL
   jobs, plus recent `chain_watcher.unknown_status` warning rate.
7. **Reference transaction hashes** — audit trail.
8. **Known open items** — non-blocking issues tracked for next sprints.

Each row that has an expected value is annotated `PASS` or `FAIL`.
A `FAIL` anywhere means something has drifted and needs investigation
before mainnet.
