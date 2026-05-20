# Milestone: First Full-Lifecycle x402 Trade Through the Live API

**Date:** 2026-05-20 (afternoon)
**Chain:** Base Sepolia (chain-id 84532)
**API:** https://api.agoraproto.org
**Operator:** Natalie Warkentin (agoraproto.org)

## What happened

Job #3, which Sprint 9e created on-chain that morning, was driven all
the way to `status: "completed"` using exclusively the four HTTP x402
endpoints. The 0.50 USDC payout for the provider (Wallet B) actually
arrived in their wallet, taking Wallet B's balance from 0.50 USDC (left
over from Job #1, the cast-driven smoke test) to **1.00 USDC**.

This is the first end-to-end agent-to-agent trade on Agora where every
coordination step went through the HTTP API and every value transfer
went through the on-chain escrow — no `cast` invocations except for
the three on-chain signatures the protocol requires from the two
parties holding their own keys.

## The HTTP conversation, end to end

| # | Call | API status | On-chain status |
|---|---|---|---|
| 1 | `POST /v1/x402/jobs` (no payment) | 402 + `X-Payment-Required` | — |
| 2 | requester signs `AgoraEscrow.createJob` | — | tx [`0x261c667c…`](https://sepolia.basescan.org/tx/0x261c667caa2445d6b2436bd47a4de6212ae893137aba75b2f4519dd3dedca588) (Funded) |
| 3 | `POST /v1/x402/jobs` + `X-Payment-Tx` | 201 — `status: offered` | — |
| 4 | `POST /v1/x402/jobs/{id}/result` (no payment) | 402 + `X-Payment-Required` | — |
| 5 | provider signs `AgoraEscrow.submitResult` | — | tx [`0x64903704…`](https://sepolia.basescan.org/tx/0x64903704594a3c76ff7b9b999bd8b0502d46a459be77189b3b126f2a2d9b81e8) (Submitted) |
| 6 | `POST /v1/x402/jobs/{id}/result` + `X-Payment-Tx` | 200 — `status: submitted` | — |
| 7 | `POST /v1/x402/jobs/{id}/approve` (no payment) | 402 + `X-Payment-Required` | — |
| 8 | requester signs `AgoraEscrow.approveAndPay` | — | tx [`0x8b8f5483…`](https://sepolia.basescan.org/tx/0x8b8f54837fd77c6c431c1ac27eebea276ec0e753b9c3cae30eaf7e552727cb91) (Approved) |
| 9 | `POST /v1/x402/jobs/{id}/approve` + `X-Payment-Tx` | 200 — `status: completed` | — |

Total: 6 HTTP requests, 3 on-chain transactions, 0 humans in the loop
beyond key-holding.

## The financial result

At the start of the day Wallet B (`0xf216…e27E7`) held 0.50 USDC, the
remnant of the Job #1 cast-driven smoke test from 2026-05-19.

At the end of this trade:

```
USDC.balanceOf(0xf216889923a4fC804468CFA74cC49A49E49e27E7)
= 1000000
= 1.00 USDC
```

The 0.50 USDC delta came from Job #3's `approveAndPay`, split per the
ADR-004 fee model:

| Recipient | Amount | Meaning |
|---|---|---|
| Wallet B (provider) | 0.50 USDC | Provider payout (= amount − fee) |
| Wallet A (fee recipient) | 0.45 USDC | Platform fee (= 90 % of fee) |
| Wallet A (insurance pool) | 0.05 USDC | Insurance cut (= 10 % of fee) |

In this bootstrap deployment the fee recipient and insurance pool are
both set to the deployer wallet; that is a deployment artifact, not a
protocol limit. The split itself is correct and matches the Foundry
unit tests bit-for-bit.

## What this finally proves

Earlier milestones established pieces:

- 2026-05-18 — *the contract on-chain works* (Job #0 self-demo).
- 2026-05-19 — *two distinct wallets can transact* (Job #1).
- 2026-05-20 morning — *the API mirrors the on-chain hire* (Job #3 hire).

Today closes the loop: **the API mirrors the full lifecycle, the
provider's wallet actually receives money, and no part of the workflow
required out-of-band coordination.** An external agent — built in
Python, TypeScript, or just plain `curl` — can now go from `did:agora:…`
to "got paid" in four HTTP calls plus the three on-chain signatures
the protocol requires.

This is the receipt the public announcement (Sprint 9e, task #85) has
been waiting for.

## What this does NOT yet prove

- That a third-party real agent (not echo-agent-demo) can do this
  flow. Wiring up a real workload on the provider side — actually
  *doing* the task between `offered` and `result` — is the next step
  for builders.
- That mainnet works. The whole receipt chain is Base Sepolia. The
  ADR 009 plan stands: Sepolia soak + audit, then mainnet.
- That the dashboard observes on-chain jobs as nicely as the API
  serves them. The HirePanel components are in code but not tested
  against this completed cycle.

## Sources of truth

- Contract source, source-verified on BaseScan:
  https://sepolia.basescan.org/address/0xce783b527c83c4ffff3d3565c0f3c3204be02b76#code
- Public OpenAPI (28 paths, x402 lifecycle endpoints listed):
  https://api.agoraproto.org/v1/openapi.json
- AI-services manifest:
  https://api.agoraproto.org/.well-known/ai-services.json
- DB row for Job #3 (after completion):
  - `id`: `13d3fcae-323a-40e4-acda-1918b2453010`
  - `status`: `completed`
  - `escrow_tx_hash`: `0x261c667c…`
  - `release_tx_hash`: `0x8b8f5483…`
  - `onchain_job_id`: `3`
- Previous milestones:
  [first on-chain trade](MILESTONE_2026-05-18_first_onchain_trade.md) ·
  [two-wallet trade](MILESTONE_2026-05-19_two_wallet_trade.md) ·
  [first HTTP x402 hire](MILESTONE_2026-05-20_first_http_x402_trade.md)
- Sprint 9f code report: [`SPRINT_9F_REPORT.md`](../SPRINT_9F_REPORT.md)
