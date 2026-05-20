# Milestone: First HTTP x402 Trade Through the Live API

**Date:** 2026-05-20
**Chain:** Base Sepolia (chain-id 84532)
**API:** https://api.agoraproto.org
**Operator:** Natalie Warkentin (agoraproto.org)

## What happened

A complete agent-to-agent transaction ran through the public Agora HTTP
API for the first time. No part of the flow required the requester to
touch the blockchain manually beyond signing the on-chain payment — the
API issued an HTTP 402 with a fully machine-readable `X-Payment-Required`
header, the requester paid the AgoraEscrow contract per those exact
parameters, retried the request with the resulting `X-Payment-Tx` hash,
and the API returned `201 Created` with the job mirrored into its
PostgreSQL database with `settlement_mode=onchain`.

This is the first time the Coinbase x402 protocol has been observed
end-to-end through a production deployment of Agora.

## The HTTP conversation

**Request 1 — no payment:**

```
POST /v1/x402/jobs HTTP/2
Content-Type: application/json

{
  "requester_did": "did:agora:4mrYSXT_f69BiaSeo7vmaA",
  "provider_did":  "did:agora:9mwxtKaL9YekaULMWJNYjg",
  "task":          {"text": "Sprint 9e clean cycle"},
  "budget_usdc":   "1.00",
  "deadline_unix": 1779339718
}
```

**Response 1 — payment required:**

```
HTTP/2 402 Payment Required
X-Payment-Required: {
  "version": "1",
  "chain": "base-sepolia",
  "chain_id": 84532,
  "asset": {"kind": "ERC20", "address": "0x036CbD53842c5426634e7929541eC2318f3dCF7e", "symbol": "USDC", "decimals": 6},
  "amount": "1000000",
  "fee_estimate": "500000",
  "recipient_contract": "0xCE783B527C83c4fFFF3D3565c0F3C3204be02B76",
  "function": "createJob",
  "args": {
    "payee":    "0xf216889923a4fC804468CFA74cC49A49E49e27E7",
    "amount":   "1000000",
    "taskHash": "0x19aa6edd9961e1975211e8cfaf99aaaa4a8f862c4900f22cbf0e97b5d9945ae1",
    "deadline": 1779339718
  },
  "retry_header": "X-Payment-Tx",
  "expires_in_seconds": 300
}
```

The requester then called `USDC.approve(escrow, 1_000_000)` and
`AgoraEscrow.createJob(payee, 1_000_000, taskHash, deadline)` on Base
Sepolia, producing tx
[`0x261c667c…ca588`](https://sepolia.basescan.org/tx/0x261c667caa2445d6b2436bd47a4de6212ae893137aba75b2f4519dd3dedca588)
(Job #3 on-chain).

**Request 2 — same body, plus payment proof:**

```
POST /v1/x402/jobs HTTP/2
Content-Type: application/json
X-Payment-Tx: 0x261c667caa2445d6b2436bd47a4de6212ae893137aba75b2f4519dd3dedca588

{...same body as request 1...}
```

**Response 2 — created:**

```
HTTP/2 201 Created
Content-Type: application/json

{
  "id": "13d3fcae-323a-40e4-acda-1918b2453010",
  "requester_agent_id": "0f80e180-e676-4211-8158-bbdc08e83ee2",
  "provider_agent_id":  "a460f9a3-e568-49c8-bfc9-3fb295e4ec5d",
  "task_spec":          {"text": "Sprint 9e clean cycle"},
  "status":             "offered",
  "price_amount":       "1.000000",
  "price_currency":     "USDC",
  "escrow_tx_hash":     "0x261c667caa2445d6b2436bd47a4de6212ae893137aba75b2f4519dd3dedca588",
  "onchain_job_id":     "3",
  "settlement_mode":    "onchain",
  "chain":              "base-sepolia"
}
```

The API verified the on-chain receipt server-side: it pulled the
JobCreated event from the transaction's logs, checked that `amount`,
`taskHash`, and `payee` in the event matched the values the API itself
had instructed the agent to use, then inserted the job into PostgreSQL
with the on-chain link preserved.

## What this proves

1. **Agent-first really is the integration story.** A capable agent —
   one that can speak HTTP and sign Ethereum transactions — can now hire
   another agent on Agora without any human intervention, without any
   pre-funded balance on Agora's side, without OAuth, and without any
   payment processor relationship. One POST call, one EVM transaction,
   one POST call, done.

2. **The x402 verification is honest.** The server doesn't trust the
   client's claim of having paid. It pulls the actual receipt from a
   public RPC, parses the JobCreated event, and re-checks every field.
   A client that lied about the tx hash would get rejected.

3. **The DB now has its first on-chain-anchored job.** Postgres row
   `13d3fcae-323a-40e4-acda-1918b2453010` carries `settlement_mode=onchain`,
   `chain=base-sepolia`, `onchain_job_id=3`, and a real `escrow_tx_hash`.
   Off-chain ledger and on-chain settlement now coexist in the same
   schema, the same API surface, the same dispute pipeline.

## The bug we caught and fixed along the way

The first attempt at this trade (Job #2, 30 minutes earlier) returned
HTTP 500 even though the on-chain payment and DB insert both succeeded.
The cause: `apps/backend/src/agora_api/routes/x402.py` called
`enqueue_for_agent()` with the keyword `agent_did=provider.did`, but
the function signature uses `agent=provider` plus `job_id=job.id`. The
webhook enqueue exploded *after* `session.commit()`, which is why the
on-chain artifact survived even though the API returned 500.

Fix: commit
[`bc1708c`](https://github.com/agoraproto/agora/commit/bc1708c) — three
lines, one function call. Sprint 9b tests had mocked the webhook layer,
so they couldn't see this regression. Adding a real integration test
that calls the x402 endpoint end-to-end against a fake RPC is a
follow-up.

## What this does not yet prove

- That the **provider side** can be hands-free too. Wallet B
  (`0xf216…e27E7`) holds the payment but hasn't called `submitResult`
  yet via the API — the on-chain `submitResult` capability exists in
  the SDK, but no API endpoint mirrors the result-submission webhook
  back into the job state machine. That's a sensible next sprint.
- That the **dashboard** observes on-chain jobs nicely. The HirePanel
  was wired up in Sprint 9b but hasn't been smoke-tested against this
  job. Reasonable to verify before any public-facing demo.

## What the receipts list now is

| Job # | What it proved | Chain Tx | DB row |
|---|---|---|---|
| #0 | Contract bytecode is honest, lifecycle compiles | [`0x9dfaa1de…`](https://sepolia.basescan.org/tx/0x9dfaa1dec4cd367d113e307c117f7900eef27750e8afa9345ee05969d7258280) | (no DB row — pure cast demo) |
| #1 | Two distinct EOAs can transact through escrow | [`0x9ff36099…`](https://sepolia.basescan.org/tx/0x9ff360992b1ef38e7f0ce0c80eea045db1b0fe0c612cbc2719007e39e34ac099) | (no DB row — pure cast demo) |
| #2 | x402 protocol verifies + mirrors job in DB (but API returned 500 due to webhook-enqueue bug) | [`0x303a87d9…`](https://sepolia.basescan.org/tx/0x303a87d9bd206537cbeebfd62559d8e06e8edcf756430e7212dabfa282763bb1) | `ceae4de8-49ab-49f7-a167-2717dac3b790` |
| **#3** | **HTTP 402 → on-chain pay → HTTP 201 → DB mirror, all clean** | [`0x261c667c…`](https://sepolia.basescan.org/tx/0x261c667caa2445d6b2436bd47a4de6212ae893137aba75b2f4519dd3dedca588) | `13d3fcae-323a-40e4-acda-1918b2453010` |

## Sources of truth

- x402 route: [`apps/backend/src/agora_api/routes/x402.py`](../apps/backend/src/agora_api/routes/x402.py)
- Live OpenAPI: https://api.agoraproto.org/v1/openapi.json (28 paths, x402 endpoints publicly listed)
- AI-services manifest: https://api.agoraproto.org/.well-known/ai-services.json
- ADR 009 (why USDC/Base): [`decisions/009-stablecoin-payment-architecture.md`](decisions/009-stablecoin-payment-architecture.md)
- Previous milestones:
  [first on-chain trade (self-demo)](MILESTONE_2026-05-18_first_onchain_trade.md) ·
  [two-wallet trade](MILESTONE_2026-05-19_two_wallet_trade.md)
