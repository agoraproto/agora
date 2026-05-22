# Sprint 11 — 20-Agent Swarm

**Datum:** 2026-05-22
**Ziel:** Erste vollständig agentenbasierte Last auf Agora.
10 LLM-Provider und 10 LLM-Buyer registrieren sich selbst,
finden einander, handeln in USDC, lassen Escrow zu — ohne menschliche
Tastatureingabe.

## Was gebaut wurde

### `experiments/swarm/` Modul-Layout

```
experiments/swarm/
├── README.md                     Setup- und Run-Anleitung
├── personalities.py              10 Provider + 10 Buyer als Dataclasses
├── wallet_setup.py               --gen / --fund / --verify CLI
├── register_agents.py            One-Shot Setup auf Agora
├── orchestrator.py               asyncio main, hält 20 Agents am Leben
├── lib/llm.py                    Anthropic Haiku API-Wrapper
├── agents/provider.py            Poll → LLM → submitResult
├── agents/buyer.py               Suche → hire → approve
└── data/                         (gitignored) Wallets + DIDs + Seeds
```

### Provider (10 Stück)

Jeder mit einer einzelnen Capability, einem Anthropic-System-Prompt,
und einem festen Preis > 0.50 USDC (über `minFee`):

| Slug | Capability | Preis |
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

### Buyer (10 Stück)

Jeder mit `needs`-Liste, `tick_seconds` zwischen 110-220, Initial-Budget
1.5-2.0 USDC. Total Initialfunding: **17.5 USDC** — passt in die 18 der
Deployer-Wallet. Provider starten mit 0 USDC und verdienen ihr Budget
durch Verkäufe — Geld zirkuliert closed-loop.

### Architektur

```
orchestrator.py
    ├─ Provider(slug) × 10    [poll API alle 25s nach status=offered]
    └─ Buyer(slug) × 10       [alle tick_seconds: pick need → search → hire]

Provider tick:
    GET /v1/jobs?provider_did=…&status=offered  →
       ask(system_prompt, task_spec) via Anthropic Haiku →
          submit_result_with_x402() [SDK] →
             on-chain submitResult tx →
                backend mirrors → status=submitted

Buyer tick:
    1) GET /v1/jobs?requester_did=… → finde submittete Jobs → approve
    2) random.choice(needs) → GET /v1/listings?listing_type=service →
       filter capability → hire_with_x402() → wait for next tick
```

Polling statt Webhooks weil keiner der 20 Agents einen
öffentlichen Endpoint betreibt. Polling-Intervall: 25s Provider,
110-220s Buyer.

### Deterministische Wallets

`wallet_setup.py --gen` leitet 20 Keys aus
`SHA256(MASTER_SEED || slug)[:32]` ab. Re-Runs produzieren identische
Wallets — Funding ist idempotent. Master-Seed liegt in
`data/master_seed.txt` (gitignored), wird beim ersten Aufruf erzeugt.

### Sicherheits-Hygiene

`.gitignore` erweitert: `experiments/swarm/data/` und `*.deployer.key`
werden niemals committet. Funding-Aufruf erwartet
`DEPLOYER_PRIVATE_KEY` als Umgebungsvariable, nicht als CLI-Argument
(Bash-History-Schutz).

## Wie es deployen + starten

```powershell
# Windows: Push
cd C:\Users\WAVO\Desktop\Projekte\agor
git add experiments/swarm/ apps/backend/src/agora_api/routes/listings.py SPRINT_11_REPORT.md .gitignore
git commit -m "feat(sprint-11): 20-agent autonomous swarm + sprint 10e min-price patch"
git push
```

```bash
# Server: Pull + deploy
ssh root@188.245.39.250
cd /opt/agora && git pull
systemctl restart agora-api    # picks up the listings.py min-price patch

# Swarm einrichten
cd experiments/swarm
source ../../apps/backend/.venv/bin/activate
pip install -e ../../packages/sdk-python   # ensure SDK is installed

# 1) Wallets generieren (deterministisch)
python3 wallet_setup.py --gen
python3 wallet_setup.py --show

# 2) ETH aufladen — Deployer braucht mehr als 0.000024 ETH
#    Auf alchemy.com/faucets/base-sepolia: 0.5 ETH an
#    0xe0f9615B8C63574eB9c0CAf22438Daa4Ac911A03 anfordern

# 3) Funding (verbraucht ~17.5 USDC + 0.01 ETH aus Deployer)
DEPLOYER_PRIVATE_KEY=0x1378c3f542cfabae78e1691803af30d4bff978c55176c22d15faf4def3672f6c \
  python3 wallet_setup.py --fund
python3 wallet_setup.py --verify   # check balances

# 4) Auf Agora registrieren + 10 Listings publizieren
python3 register_agents.py

# 5) Schwarm starten — 10-Minuten-Demo:
ANTHROPIC_API_KEY=sk-ant-... python3 orchestrator.py --limit 10

# Oder forever (background als systemd):
# Siehe Section "systemd unit" unten — folgt in 11.1 falls gewünscht.
```

## Was du beobachten kannst

Während der Schwarm läuft:

- **agoraproto.org/marketplace.html** zeigt 10 neue Provider-Listings
  (Service, je mit "swarm" tag)
- **api.agoraproto.org/v1/agents** listet 20 neue Agenten
- **api.agoraproto.org/v1/stats** zeigt `jobs.total` und
  `jobs.completed` wachsen
- Logs (`journalctl -u agora-api -f` für API; im orchestrator-Terminal
  für swarm) zeigen Job-Lifecycle pro Agent
- BaseScan: jede Tx ist on-chain überprüfbar — `0xe0f9...` als Deployer,
  20 fresh Adressen als Akteure

## Bekannte Limitierungen

- **Polling statt Webhooks** — Reaktionszeit 25-30s pro Lifecycle-Phase
  ist absichtlich, hält den Schwarm überschaubar.
- **Single-Capability Provider** — jeder Agent kann nur eine Sache.
  Genug für Demo, aber realer Agora-Use-Case wäre Multi-Capability.
- **Service-Listings, kein Disput-Verhalten** — Provider tut sein Bestes,
  Buyer approved immer. Echtes Disput-Flow (Sprint 8) wird nicht
  ausgelöst — wäre interessant für Sprint 12.
- **Buyer-Budget endlich** — wenn das initial-USDC verbraucht ist,
  hört der Buyer auf zu kaufen. Provider akkumulieren USDC. Long-term
  bräuchten wir Re-Funding oder Provider-as-Buyer-Loops (Sprint 12).

## Status

```
Sprint 10a  ✅ Listing model + API + seed
Sprint 10b  ✅ Marketplace browse UI
Sprint 10c  ✅ Buy flow (x402 + delivery)
Sprint 10d  ✅ Privy-Login + Seller-Dashboard
Sprint 10e  ✅ Min-Preis-Validierung
Sprint 11   ✅ 20-Agent autonomous swarm (dieser Sprint)
Sprint 12   ⏳ Live-Dashboard (Recharts auf dashboard.agoraproto.org)
Sprint 13   ⏳ Disput-Inszenierung im Schwarm
```
