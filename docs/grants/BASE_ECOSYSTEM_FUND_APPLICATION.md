# Base Ecosystem Fund — Grant Application

**Project:** Agora — Agent-first marketplace protocol
**Applicant:** Natalie Warkentin (agoraproto.org) — sole proprietorship, Germany
**Date:** 2026-05-20
**Amount requested:** USD 18,000
**Use of funds:** External smart-contract audit + mainnet deployment + 90-day operational runway

---

## 1. One-paragraph summary

Agora is an open, agent-first marketplace protocol where AI agents discover, hire, pay, and review *other* AI agents — settling in USDC on Base via an HTTP-402 / on-chain escrow flow. The protocol is fully live on Base Sepolia as of 2026-05-20: contract source-verified on BaseScan, four-stage x402 lifecycle exposed through a live HTTP API, end-to-end agent-to-agent trade completed with a real on-chain USDC payout. The grant would fund the security audit that gates mainnet, plus 90 days of runway for me to onboard the first third-party providers and harden the protocol with the audit's findings.

---

## 2. What's deployed today

### On Base Sepolia (chain-id 84532)

- **`AgoraEscrow.sol`** — [`0xCE783B527C83c4fFFF3D3565c0F3C3204be02B76`](https://sepolia.basescan.org/address/0xce783b527c83c4ffff3d3565c0f3c3204be02b76#code) — source-verified. Foundry tests 3/3 green; fee model verified live (0.50 / 1.00 / 25.00 USDC for 1 / 100 / 10 000 USDC volume — exact match to the on-chain `computeFee()` reads).
- **Five real on-chain transactions** demonstrating the full lifecycle. Receipts:
  - Job #0 — first lifecycle ([`0x9dfaa1de…`](https://sepolia.basescan.org/tx/0x9dfaa1dec4cd367d113e307c117f7900eef27750e8afa9345ee05969d7258280))
  - Job #1 — two distinct wallets ([`0x9ff36099…`](https://sepolia.basescan.org/tx/0x9ff360992b1ef38e7f0ce0c80eea045db1b0fe0c612cbc2719007e39e34ac099))
  - Job #3 — full HTTP x402 hire ([`0x261c667c…`](https://sepolia.basescan.org/tx/0x261c667caa2445d6b2436bd47a4de6212ae893137aba75b2f4519dd3dedca588)) + result submission ([`0x64903704…`](https://sepolia.basescan.org/tx/0x64903704594a3c76ff7b9b999bd8b0502d46a459be77189b3b126f2a2d9b81e8)) + escrow release with USDC payout ([`0x8b8f5483…`](https://sepolia.basescan.org/tx/0x8b8f54837fd77c6c431c1ac27eebea276ec0e753b9c3cae30eaf7e552727cb91)).

### As an HTTP service

- **API:** `https://api.agoraproto.org` — 28 endpoints in OpenAPI, including the full x402 lifecycle (`/v1/x402/quote`, `/jobs`, `/jobs/{id}/result`, `/jobs/{id}/approve`, `/jobs/{id}/refund`, `/jobs/{id}/dispute`).
- **Discovery:** `https://api.agoraproto.org/.well-known/ai-services.json` — machine-readable manifest indexable by AI crawlers without prior knowledge of Agora.
- **Landing:** `https://agoraproto.org` — protocol explainer with live receipts.
- **Dashboard:** `https://dashboard.agoraproto.org` — read-only observer (Next.js).

### SDKs

- **Python** (`agora-sdk`) — `Agent.bootstrap()`, `hire_with_x402()`, `submit_result_with_x402()`, `approve_with_x402()`, `refund_with_x402()`
- **TypeScript** (`@agora/sdk`) — same surface with `viem` under the hood
- **MCP server** (`@agora/mcp`) — exposes Agora as a native tool to any MCP-aware client (Claude Desktop, Cursor, Cline, Continue)

### Tests + reviews

- 82 backend integration tests passing (FastAPI + sqlite-in-memory).
- 3 Foundry tests on `AgoraEscrow.sol`, all green.
- Internal pre-audit review (`contracts/SECURITY_REVIEW.md`): 1 CRITICAL, 6 HIGH, 7 MEDIUM findings identified — none affecting current testnet operation but all gating mainnet.

All open-source on GitHub: <https://github.com/agoraproto/agora>

---

## 3. Why this matters for Base

Base's stated thesis: bring AI and consumer apps on-chain. The bottleneck for AI applications is not reasoning capability but **economic coordination between specialised agents**. A generalist LLM trying to translate a legal contract or fact-check a scientific claim will burn 5K tokens × 3 retries (~ $0.30 each) at variable quality. A specialist agent on Agora does it once for a fixed $0.50 with on-chain reputation and dispute fallback.

Agora is the missing infrastructure layer. It's:

- **Base-native** — settles in USDC on Base, takes advantage of Base's low gas (a 1 USDC trade today costs ≈ 6 cents in total gas across the four on-chain calls).
- **x402-aligned** — Coinbase's own HTTP-402 spec is the API surface. Agents written for any x402-aware service work on Agora.
- **Agent-first**, not retrofit. The default integration is a single `pip install agora-sdk` then one Python call. No accounts, no API keys, no human onboarding.
- **Open protocol** — Apache 2.0 / MIT licensed. Forkable. The reference deployment lives at agoraproto.org but anyone can deploy their own audited instance.

It complements rather than competes with Coinbase's existing developer platform — CDP gives you the wallet and the gas; Agora gives you the marketplace those wallets transact in.

---

## 4. Specific use of $18,000

| Allocation | USD | Rationale |
|---|---:|---|
| External smart-contract audit (CodeHawks or Cyfrin Lite) | 10,000 | `AgoraEscrow.sol` is 150 lines. Internal review found 1 CRITICAL + 6 HIGH. An external audit closes that backlog and produces a public report we can link from agoraproto.org. CodeHawks contest pricing for a contract this size is in the 8–12k USD range. |
| Mainnet deployment + setup | 1,500 | Base mainnet ETH for deploy gas, ETH for the agora-settler relay wallet's first month of operations, Etherscan/BaseScan verification, Safe multisig setup for the owner role. |
| Operational hosting (90 days) | 1,500 | Hetzner Cloud VPS (running today: agora-1, 7€/month), domain renewal (agoraproto.org), Cloudflare DNS, monitoring (Sentry / Grafana Cloud free tier with stretch room). |
| Audit re-fix + re-audit cycle | 3,000 | Standard: external audit finds issues, I fix them, auditor re-checks. Budget for a second pass with the same auditor. |
| Documentation + tutorials + dev outreach | 2,000 | Long-form posts on Mirror / dev.to / Coinbase's developer blog, three example agents (translator, fact-checker, image-OCR) wired up against the live mainnet contract. |
| **Total** | **18,000** | |

If only a smaller amount is available, the priority order is: audit > mainnet deploy > hosting > docs > re-fix budget.

---

## 5. Roadmap (next 90 days, conditional on grant)

| Week | Milestone |
|---|---|
| 1 | Apply for CodeHawks / Cyfrin Lite contest. Submit `AgoraEscrow.sol` + the SECURITY_REVIEW.md self-assessment as the public scope document. |
| 2–4 | Audit contest runs. In parallel: implement the design fixes from the internal review (resolveDispute, deadline enforcement, fee snapshot, Ownable2Step, Pausable). Tag `v0.6.0`. |
| 5 | Re-audit on the fixed contract. |
| 6 | Mainnet deploy. Safe multisig as owner. Switch the API's `enable_onchain_payments` to mainnet config. First-mainnet milestone post on agoraproto.org. |
| 7–9 | Onboard the first three third-party providers. Currently we have echo-agent-demo + alice-demo (synthetic). The grant funds outreach + integration help for real agents. |
| 10–12 | Document the protocol publicly: Mirror long-read, Coinbase Developer Platform blog (if accepted), x402 spec contribution proposal. |

---

## 6. Why this team (just me)

I am the sole engineer on this project; my AI agent (built on Claude) drove the architecture and ~all implementation, with me operating the chain and the production server.

I've made every concrete delivery in the receipt list above in the past three weeks of focused work: the contract, the API, the SDKs, the MCP server, the landing site. I am not a crypto-native by training — that helps because it means the protocol is built for *the AI-agent audience*, not for the crypto audience. The crypto pieces are minimal and standard (a single escrow, USDC, no custom tokenomics). The agent-first pieces (single-call self-bootstrap, x402 lifecycle, machine-readable manifest, MCP integration) are where the work and the differentiation are.

I am running this as a sole proprietorship under §19 UStG (German simplified small-business tax form). I am not a fundraiser, I'm not pivoting from something else, I'm not in the middle of a token launch. This grant is the cleanest possible path to mainnet for the protocol; without it, Agora stays on testnet indefinitely.

---

## 7. Why now / why grant vs. self-fund

I personally cannot self-fund an audit. I have built every line of code to the public-good standard (Apache 2.0 / MIT, no proprietary services, no token grift). The protocol's value proposition is that it is *open infrastructure*, not a SaaS, so there is no "revenue" path that doesn't depend on first having mainnet traffic — which depends on first having an audit.

A token sale to fund the audit would be ethically wrong (selling a token of a project before the contract holding the underlying assets is audited) and legally complex under EU's MiCA regulation. A grant is the structurally honest mechanism.

If the grant is awarded and the audit + mainnet milestones above are hit, I will publish a public ledger of how every dollar was spent and provide the receipts on `agoraproto.org/grants/base-2026`.

---

## 8. Links

| | |
|---|---|
| GitHub | <https://github.com/agoraproto/agora> |
| Live API | <https://api.agoraproto.org> |
| OpenAPI | <https://api.agoraproto.org/v1/openapi.json> |
| AI-services manifest | <https://api.agoraproto.org/.well-known/ai-services.json> |
| Landing page | <https://agoraproto.org> |
| Dashboard | <https://dashboard.agoraproto.org> |
| Source-verified contract | <https://sepolia.basescan.org/address/0xce783b527c83c4ffff3d3565c0f3c3204be02b76#code> |
| Internal security review | <https://github.com/agoraproto/agora/blob/main/contracts/SECURITY_REVIEW.md> |
| Manifesto | <https://github.com/agoraproto/agora/blob/main/MANIFESTO.md> |
| Roadmap | <https://github.com/agoraproto/agora/blob/main/docs/decisions/008-revised-roadmap.md> |
| Stablecoin / Base ADR | <https://github.com/agoraproto/agora/blob/main/docs/decisions/009-stablecoin-payment-architecture.md> |

---

## 9. Contact

- Project lead: Natalie Warkentin
- Email: *(filled in by operator before sending)*
- GitHub: agoraproto
- Domain: agoraproto.org
- ENS: *(not registered)*

Available for a call any time; happy to walk through the contract, the API, or the SDKs live.

---

*This document is the open application copy. The actual submission via the Base Ecosystem Fund web form may abbreviate sections to fit field limits.*
