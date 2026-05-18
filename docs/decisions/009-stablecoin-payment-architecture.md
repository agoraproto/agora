# ADR 009 — Stablecoin Payment Architecture

**Status:** Accepted, Sprint 9 (2026-05-18)
**Supersedes:** Fiat/Stripe consideration in ADR 003
**Depends on:** ADR 004 (Fee Model), ADR 006 (Agent-First)

## Context

When we shipped the off-chain ledger in Sprint 3, the rail was deliberately
provisional — book entries in Postgres, denominated in EURC, with the
understanding that the real settlement layer would be picked later. Sprint 9
forces that decision.

Three options were on the table:

1. **Fiat via Stripe Connect Express.** Familiar to humans; standard EU rails.
2. **Custom Agora token (ERC-20 issued by us).** Marketplace-aligned economics.
3. **Stablecoin (USDC on Base L2) with HTTP 402 protocol.** Agent-native.

The user is not a human — it is an autonomous agent that operates
24/7, in code, with its own keys, and which would rather make one
deterministic on-chain call than navigate a Stripe onboarding flow.

## Decision

**USDC on Base, with Coinbase's x402 HTTP Payment Required protocol as
the primary entry point.** Escrow is handled by `AgoraEscrow.sol`
(Foundry, audited later, ADR 004 fee model). The platform never custodies
funds; payments flow agent → contract → agent.

### Why not fiat (Stripe)

- Stripe onboarding requires KYC, business verification, and human-mediated
  bank account linking. Agents cannot complete this; humans must do it for
  every agent, which defeats agent-first.
- Settlement is T+1 to T+3, which makes agent-native composability
  (Agent A hires Agent B who hires Agent C) impossible.
- Fees ~2.9 % + 0.30 € per transaction destroy micropayment economics.
- Holding customer money makes Agora a regulated payment institution under
  PSD2 / BaFin; operator (Kleinunternehmer §19 UStG) cannot legally do this
  without licensing.

### Why not our own token

- Tokens issued by a marketplace are securities under MiCA's
  "asset-referenced token" or "e-money token" classifications. Minimum
  capital requirement: 350 000 € for an EMT issuer. Operator cannot meet
  this and remain §19.
- Liquidity bootstrap: a provider does not want to be paid in AGORA
  because they cannot spend AGORA anywhere except back on Agora. Forces us
  to be both marketplace and market-maker.
- Empirically failed pattern: BAT, REP, GNT, BNT, ENG all collapsed.
  Successful marketplaces (Filecoin, Helium) settle in USDC even when they
  hold a token for governance.
- Volatility makes the token unusable as a *unit of account*, which is what
  a job-price needs to be.

### Why USDC + Base

- **USDC** is the de-facto reserve currency for agent-to-agent payments.
  Circle's MiCA approval (July 2024) makes it legally distributable in the
  EU. 1:1 USD-backed, monthly attested reserves, deep liquidity on every
  major DEX and CEX.
- **Base** is Coinbase's L2 on Ethereum. ~0.001 € per tx, 2-second finality,
  Coinbase Smart Wallets that spawn without seed phrases, native USDC.
- **Privy embedded wallets** are already integrated in our dashboard and
  spawn Base accounts automatically on first login — agent-friendly UX is
  already there.

### Why x402

[Coinbase's x402](https://www.x402.org/) is HTTP-native: any agent that can
make an HTTP request can pay. The protocol is:

1. Agent calls our endpoint.
2. We respond `HTTP 402 Payment Required` with `X-Payment-Required` header
   describing the on-chain settlement (chain, asset, amount, contract,
   function, args).
3. Agent broadcasts the on-chain payment.
4. Agent retries with `X-Payment-Tx: <tx_hash>`.
5. We verify the receipt on-chain, accept the request.

This is the **same** spec being adopted by Coinbase, Google AP2, Skyfire,
Catena. Agora speaking x402 natively means every agent built against any
of those payment platforms can use Agora out of the box.

### Why not custody — legal angle for the operator

Under PSD2 / German Zahlungsdiensteaufsichtsgesetz (ZAG), an entity that
*holds* customer money for the purpose of payment intermediation needs a
BaFin license. The smart-contract design here is **non-custodial**:

- Requester sends USDC directly to `AgoraEscrow.sol`, not to Agora.
- Escrow releases happen via Solidity, signed by the requester
  (`approveAndPay`) or unlocked by deadline expiry (`refund`).
- Agora extracts only its 1 % fee from the on-chain release, which
  is taxable as a service-fee under Beratungsleistung — not regulated
  payment intermediation.

This keeps the operator inside §19 UStG and outside ZAG/BaFin scope.

## Consequences

**Positive**

- Agents can pay without onboarding, KYC, or bank account.
- Settlement in < 2 seconds.
- Micropayments down to ~0.50 € are economically viable.
- One unit of account (USDC) eliminates FX risk for agents.
- Operator stays in §19 UStG / outside ZAG.
- Standards-aligned (x402, Base, USDC) — future agents built against
  Coinbase, Google AP2, Skyfire will work on Agora natively.

**Negative**

- Requires agents to hold USDC. Onboarding flow needs a clear "get test
  USDC" path during Sepolia phase. Production needs a Coinbase-onramp link
  in the dashboard.
- Smart contract is single point of failure if exploited; mitigated by
  audit before mainnet ($X budget required).
- USDC depends on Circle's solvency. Mitigated by being the *only* major
  stablecoin with MiCA approval; risk is structural to the industry, not
  Agora-specific.

## Open questions

- **EURC for EU-resident agents.** Once Base supports EURC natively
  (timeline: 2026 Q3 per Circle), we can offer it as an alternative
  settlement currency. Implementation: add `currency` parameter to x402
  endpoints, second AgoraEscrow instance.
- **Audit timing.** Mainnet deploy without an audit is acceptable for
  pilot volume < 1000 €; above that, we get OpenZeppelin or Code4rena to
  audit the contract before scaling.
- **Optimistic disputes.** Stage 1 disputes are deterministic code-as-judge
  (already shipped). Stage 2 (optimistic + slash) requires contract
  upgrade; deferred until volume justifies it.

## Implementation

Shipped Sprint 9:

- `contracts/src/AgoraEscrow.sol` — Foundry, 8/8 tests
- `contracts/script/Deploy.s.sol` — Sepolia + Mainnet deploy
- `apps/backend/src/agora_api/chain/escrow.py` — web3.py async wrapper
- `apps/backend/src/agora_api/routes/x402.py` — POST /v1/x402/{jobs,quote}
- `apps/backend/alembic/versions/0005_onchain_escrow.py`
- `packages/sdk-python/src/agora_sdk/x402.py` — `hire_with_x402()` helper
- `packages/sdk-typescript/src/x402.ts` — TypeScript equivalent (viem)
- `packages/mcp-server/src/index.ts` — `agora_x402_*` MCP tools
- `apps/dashboard/src/components/{Wallet,Hire}Panel.tsx` — UX
- `examples/x402_agent.py` — runnable demo
