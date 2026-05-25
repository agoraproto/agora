# Agora — Project Constants & House Rules for Claude

Living memory for sprint-to-sprint work. Read this before starting any
sprint or before defaulting values like prices, fees, or budgets.

## House rules (Andreas)

### Pricing — STRICT

**Every listing on Agora costs ≤ 0.01 USDC. No exceptions.**

Agora is a micro-transaction marketplace **between AI agents**. A buyer
agent making 10 000 API calls per day won't spend €2.50 per call —
they'll route around anything that expensive. Realistic ceiling is
≤ 1 ct per service call. B2B-SaaS pricing (1-50 USDC per call) does not
belong here, even if a human-equivalent service would cost more.

When in doubt, pick **0.01 USDC** as the default.

On-chain `minFee = 0` (Sprint 16), so 0.01 USDC is the floor that
clears the escrow contract.

Existing swarm listings (0.50–0.90 USDC) are legacy from before this
rule — leave them for now, but no new listing should be above 0.01.

### Stake — keep at 0 EUR for bootstrap agents

The bootstrap endpoint (Sprint 19) registers agents with `stake_eur = 0`
and `trust_level = probation`. Don't change this unless Andreas
explicitly approves a stake.

### Deploy — auto-pull does the heavy lifting

- Push to `main` via `/tmp/agora-clone` using the PAT (already set up).
- The server (`agora-1`, 188.245.39.250) runs `agora-autopull.timer`
  every 30 s and surgically restarts affected services:
  - `apps/backend/*` → `agora-api.service`
  - `apps/website/*` → reloads Caddy
  - `experiments/swarm/*` → `agora-swarm.service`
- Anything outside those paths (new experiment folders, new systemd
  units) needs **one manual `bash setup_*.sh` on the server** —
  Andreas runs it because Claude has no SSH.

### Don't commit secrets

GitHub secret scanning has blocked us before. Keys live in:
- `/opt/agora/experiments/swarm/.env` (Anthropic) — mode 600
- `/opt/agora/experiments/swarm/.deployer-key` (Sepolia deployer) — mode 600

The Anthropic key embedded in an early `deploy_to_server.sh` is burned
and needs rotation (open todo).

### Mount-lag bug — verify before push

The sandbox's view of `C:\Users\WAVO\Desktop\Projekte\agor` sometimes
truncates files >100 lines mid-write. **Always** verify with
`wc -l` + `python3 -m py_compile` (or `bash -n`) inside
`/tmp/agora-clone` before committing.

## Constants

| Thing | Value |
|---|---|
| Chain | Base Sepolia |
| Chain ID | 84532 |
| RPC | `https://sepolia.base.org` |
| USDC contract | (see `apps/backend/src/agora_api/config.py`) |
| Escrow contract | AgoraEscrow.sol |
| Platform fee | 10 bps (0.1%) — Sprint 16 |
| Min fee | 0 USDC — Sprint 16 |
| Max fee | 25 USDC |
| API base | `https://api.agoraproto.org` |
| Website | `https://agoraproto.org` |
| Live dashboard | `https://agoraproto.org/live.html` |
| Admin dashboard | `https://agoraproto.org/admin.html` (basic auth) |
| Server | root@188.245.39.250 (`agora-1`) |
| LLM model | `claude-haiku-4-5-20251001` |

## Sprint shorthand

- **Sprint 11**: 20-agent swarm (10 providers + 10 buyers)
- **Sprint 13**: swarm as systemd service
- **Sprint 14**: auto-topup timer
- **Sprint 15**: admin dashboard
- **Sprint 16**: fees → 0.1%, min → 0
- **Sprint 17**: self-service deploy (PAT + auto-pull)
- **Sprint 18**: UX fixes (reviews-in-approve, USDC consistency)
- **Sprint 19**: POST /v1/agents/bootstrap (Ed25519 + EVM + DID + fund in one call)
- **Sprint 20**: Audit Document Gap Checker (first non-swarm autonomous agent)
- **Sprint 20b**: price rule — all listings ≤ 0.01 USDC
