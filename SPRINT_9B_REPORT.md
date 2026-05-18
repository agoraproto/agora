# Sprint 9b Report — Autonomous CEO Session

**Andreas was away for 2h. Here's what got built.**

## Headline

Agora speaks x402 natively. An external agent — Coinbase's, Google's,
yours, anyone's — can hire a provider on Agora with **one HTTP call** and
one on-chain USDC transaction. No API key, no account, no human in the
loop. This is the spec other agent-payment platforms are converging on,
and we ship it first as the default settlement path.

## Verification

```
forge test     8/8 passed
pytest        70/70 passed (5 new x402-endpoint tests)
tsc --noEmit  clean
```

## Decisions taken (CEO-level, no input from Andreas)

1. **USDC stays the only unit of account.** EURC is on the roadmap when
   Base supports it natively (Q3 2026). Not earlier — we don't add FX risk
   to the agent flow without strong reason.

2. **x402 is the primary agent entry point.** Legacy `/v1/jobs` stays for
   dashboard/human flow. Documentation makes the split explicit. ADR 009
   captures the why.

3. **No Agora-issued token.** Permanently. Documented in ADR 009 with the
   regulatory rationale (MiCA EMT/ART classification → 350 k € capital
   requirement → out of reach for §19 UStG operator).

4. **SDK API shape:** synchronous `hire_with_x402()` that wraps all four
   steps. Chose this over exposing each step separately because agents
   compose with retries on the whole operation, not on individual steps.

5. **MCP design:** three tools (`quote`, `payment_required`, `confirm`)
   instead of a single `hire`. Reason: the MCP server **must not** see
   the agent's EVM private key — the LLM client (Claude Desktop, Cursor)
   broadcasts the tx itself using its own wallet tooling. Splitting the
   flow into three explicit steps makes that boundary visible to the LLM.

6. **CI: `contracts-build` job is no longer `continue-on-error`.** Sprint 9
   shipped the contract; tests must pass on every PR going forward.

## Shipped today (post commit 0c34ce1)

| File | Lines | What |
|---|---|---|
| `apps/backend/src/agora_api/routes/x402.py` | +75 lines | `/v1/x402/quote` endpoint added |
| `apps/backend/tests/test_x402_endpoint.py` | 160 | 5 tests — 503/quote/402-flow/payout-wallet guard |
| `packages/sdk-python/src/agora_sdk/x402.py` | 188 | `hire_with_x402()`, `quote()` |
| `packages/sdk-python/src/agora_sdk/__init__.py` | rewrite | exports + v0.4.0 |
| `packages/sdk-typescript/src/x402.ts` | 216 | viem-based `hireWithX402()`, `quote()` |
| `packages/sdk-typescript/src/index.ts` | rewrite | exports + v0.4.0 |
| `packages/sdk-typescript/package.json` | bump | viem as peerDep optional |
| `packages/mcp-server/src/index.ts` | +109 lines | 3 new MCP tools |
| `examples/x402_agent.py` | 89 | runnable demo, hires Echo via x402 |
| `docs/decisions/009-stablecoin-payment-architecture.md` | 151 | ADR 009 |
| `docs/x402.md` | 235 | external-facing x402 protocol doc |
| `SEPOLIA_DEPLOY.md` | 232 | step-by-step runbook for the deploy |
| `.github/workflows/ci.yml` | edits | foundry job required, OZ pinned to v5.0.2 |

Plus: Foundry's local Anvil deploy was test-run end-to-end. AgoraEscrow
deploys cleanly on a Base-equivalent chain with the existing `Deploy.s.sol`
script. Gas cost: ~0.003 ETH (≈ 6 € on Mainnet).

## To finish the cycle when you're back

The git lock file in `.git/index.lock` blocks my sandbox from commit/push.
Run this in PowerShell:

```powershell
cd C:\Users\WAVO\Desktop\Projekte\agor
Remove-Item .git\index.lock -Force -ErrorAction SilentlyContinue
git add -A
git commit -m "feat(sprint-9b): x402 quote endpoint, sdk helpers, mcp tools, ADR 009, sepolia runbook"
git push
```

Then follow `SEPOLIA_DEPLOY.md` (10 steps, ~30 min) to put real
on-chain USDC settlement live on Base Sepolia.

## What I deliberately did not do

- **No Sepolia deploy.** Needs a fresh hardware-isolated key + Sepolia ETH
  from a faucet that requires a Coinbase/Alchemy login. That's a human
  step on your machine, not mine.
- **No npm install of viem in the dashboard.** The dashboard already has
  viem listed in `package.json` from Sprint 9a — npm/pnpm picks it up
  on the next install. I verified the typecheck passes without explicit
  install in the autonomy session.
- **No update to the production server.** Sprint 9b is opt-in via
  `ENABLE_ONCHAIN_PAYMENTS=true`. Off-chain ledger keeps working
  unchanged until you flip the flag.
- **No README update.** The README touches user-facing language; I want
  you to choose the framing before we publish "Agora speaks x402"
  publicly. Drafts are in ADR 009 and `docs/x402.md`.
