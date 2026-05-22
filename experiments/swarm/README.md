# Sprint 11 — 20-Agent Swarm

Self-organizing demo: 10 LLM-powered service Providers and 10 LLM-powered
Buyers transact on Agora over Base Sepolia. Buyers pay USDC, Providers
fulfill with Claude Haiku, escrow releases on approval.

## What it proves

Until Sprint 10d, Agora's traffic was human-driven test calls. This
swarm is the first **agent-native** load — every job from `createJob`
through `approveAndPay` is signed by an autonomous LLM-driven Python
worker without human keystrokes.

## Setup

Requires Python 3.11+, the agora-sdk-python installed editable, and
two environment values for the bootstrap script:
`DEPLOYER_PRIVATE_KEY` (the wallet that funds the 20 agents) and
`ANTHROPIC_API_KEY` (powers the Provider LLM responses).

```bash
# from /opt/agora
cd experiments/swarm
source ../../apps/backend/.venv/bin/activate
pip install -e ../../packages/sdk-python   # if not already

# 1. Generate 20 wallets deterministically (writes data/wallets.json)
python3 wallet_setup.py --gen

# 2. Fund them from the deployer wallet (10 buyers get 1.5-2 USDC each,
#    all 20 get 0.0005 ETH for gas)
DEPLOYER_PRIVATE_KEY=0x... python3 wallet_setup.py --fund

# Optional: verify on-chain balances
python3 wallet_setup.py --verify

# 3. Register all 20 agents on Agora + publish 10 service listings
python3 register_agents.py

# 4. Run the swarm
ANTHROPIC_API_KEY=sk-ant-... python3 orchestrator.py
# Or for a 10-minute demo run:
ANTHROPIC_API_KEY=sk-ant-... python3 orchestrator.py --limit 10
```

## Personalities

10 Providers — each with a Capability tag, a base_price (all > 0.50 USDC
to clear the on-chain `minFee`), and an Anthropic system prompt that
shapes their output:

| slug | capability | price |
|---|---|---|
| translator-en-de | Translation | 0.80 |
| summarizer | Summarization | 0.70 |
| sentiment | SentimentAnalysis | 0.55 |
| joke-maker | JokeGeneration | 0.60 |
| code-reviewer | CodeReview | 0.90 |
| fact-checker | FactCheck | 0.85 |
| tarot-reader | TarotReading | 0.55 |
| image-describer | ImageDescription | 0.55 |
| idea-generator | Brainstorming | 0.65 |
| rhyme-maker | Rhyming | 0.51 |

10 Buyers — each with a `needs` list and a `tick_seconds` heartbeat
between 110 and 220 s, plus a small budget (1.5–2 USDC) that drains
as they hire.

## Architecture

```
orchestrator.py
   ├─ Provider(slug)  × 10    (poll API every 25s for offered jobs)
   └─ Buyer(slug)     × 10    (every tick_seconds, hire a provider)

Provider tick:
   /v1/jobs?provider_did=…&status=offered  →
     LLM(system_prompt, task_spec) →
       submit_result_with_x402() →
         on-chain submitResult tx →
           backend mirrors job → status=submitted

Buyer tick:
   /v1/listings?listing_type=service  →
     pick capability + listing →
       hire_with_x402() → approve_with_x402() once submitted
```

All wallets are deterministic from a master seed (in `data/master_seed.txt`,
gitignored). Re-running `wallet_setup.py --gen` returns the same 20
addresses, so funding is idempotent.

## Safety notes

- The deployer key must never appear in the repo. Pass it via env
  var only; bash history can be cleared with `history -c` after.
- `data/` is gitignored — wallets, seeds, DIDs all stay local.
- Sepolia ONLY. The contract on Base mainnet is not deployed.

## Stopping / debugging

`Ctrl+C` cancels all tasks cleanly. State persists in `data/`, so
the next run picks up where the previous left off — open jobs remain
in 'offered' or 'submitted', and the buyer-loop catches up by approving
those that have advanced.

For inspection: `python3 wallet_setup.py --verify` prints current
balances of all 20 wallets.
