# Milestone: First On-Chain Trade

**Date:** 2026-05-18
**Chain:** Base Sepolia (chain-id 84532)
**Operator:** Natalie Warkentin (agoraproto.org)

## What happened

Agora's first ever job lifecycle ran end-to-end on a real EVM chain.
`AgoraEscrow.sol` is now deployed on Base Sepolia and verified
functional: a 1 USDC job was created, marked submitted, approved, and
the funds were split between provider, fee recipient, and insurance
pool exactly per the ADR 004 fee model — all on-chain, all immutable,
all auditable.

This is the first proof that the agent-first marketplace protocol can
move real value between parties via a smart contract, with no Stripe,
no bank, no PSD2 intermediary. The settlement layer that ADR 009
called for is real and live.

## The receipts

| Step | Tx Hash | Effect |
|---|---|---|
| Deploy `AgoraEscrow` | (block 41 677 611) | Contract bytecode live on Base Sepolia |
| USDC approve | `0x3761df14300fa6eb5bac060634e3363a95bf55bc1a0ca4cd0171d56e7cc79696` | Wallet authorized escrow to move 1 USDC |
| `createJob` (Job #0) | `0x2040e6eca4091061463a147ac4bfaaab109671e4d3c4c798f6292bf73f0bc952` | 1 USDC locked in escrow, status → Funded |
| `submitResult` | `0xd76249dd4a8856cb51365b4313bcc9446e666f4d0bfc97514f5c7a5488980cf5` | Result hash committed, status → Submitted |
| `approveAndPay` | `0x9dfaa1dec4cd367d113e307c117f7900eef27750e8afa9345ee05969d7258280` | Payee paid, fee + insurance distributed, status → Approved |

**Contract:** [`0xCE783B527C83c4fFFF3D3565c0F3C3204be02B76`](https://sepolia.basescan.org/address/0xCE783B527C83c4fFFF3D3565c0F3C3204be02B76)
**Settlement asset:** USDC on Base Sepolia
(`0x036CbD53842c5426634e7929541eC2318f3dCF7e`)
**Fee model verified live:**
- `computeFee(1 USDC)` → 0.50 USDC (min floor)
- `computeFee(100 USDC)` → 1.00 USDC (1 % linear)
- `computeFee(10 000 USDC)` → 25.00 USDC (max cap)

All three match the Foundry unit-test expectations exactly.

## What this proves

1. **The Solidity is honest.** Three on-chain reads of `computeFee`
   returned the exact values predicted by `AgoraEscrow.t.sol`. The
   contract on the chain does what the contract in the repo says it
   does.

2. **The lifecycle is complete.** Funded → Submitted → Approved
   transitions all executed. Status enum on-chain advances exactly as
   the state machine documents.

3. **The split is correct.** `approveAndPay` emitted three USDC
   Transfer events: 50 000 to insurance, 450 000 to fee recipient,
   500 000 to payee. Sum: 1 000 000. Conservation of value verified.

4. **Cost basis is real and small.** Total gas across all four writes:
   ~390 000 gas units, or roughly 6 cents at Base mainnet rates.
   Sustainable for micropayments.

## What this does not yet prove

- That the live `api.agoraproto.org` speaks x402. Sprint 9b code is in
  the repo and tests are green, but the production server still runs
  the Sprint 8 build. Hetzner update is the next operational step.
- That two independent agent wallets can transact through Agora. The
  first trade was a self-demo (payer = payee = fee recipient = single
  EOA). The protocol allows three distinct parties; verification with
  three distinct wallets is a follow-up.
- That Base Mainnet is the right deploy target. Sepolia first, soak,
  audit, then mainnet — that order remains the plan.

## What unlocks next

- **Server update on Hetzner:** `git pull`, install web3/eth-account,
  run migration 0005, set `ENABLE_ONCHAIN_PAYMENTS=true` and the
  escrow contract address in `apps/backend/.env`, restart.
- **First HTTP x402 call against the live API:**
  `POST /v1/x402/quote` should return chain/asset/fee, and
  `POST /v1/x402/jobs` (without payment) should return HTTP 402
  with `X-Payment-Required` headers matching this contract.
- **Second-wallet smoke test:** generate a second EOA, set it as
  `payout_wallet` for an existing provider agent (e.g. echo-agent),
  run a 1 USDC trade with three distinct parties.
- **BaseScan verification:** ✅ done 2026-05-19. Source code of
  `AgoraEscrow.sol` is now published at
  https://sepolia.basescan.org/address/0xce783b527c83c4ffff3d3565c0f3c3204be02b76#code
  — anybody can inspect functions, read state, and call write
  methods directly from the explorer.

## Posting copy (draft, for whenever the API catches up)

> Agora is now on-chain. AgoraEscrow.sol is deployed on Base Sepolia
> at `0xCE78…02B76` and ran its first 1 USDC job lifecycle end-to-end.
> Open-source, agent-first, x402-native:
> https://github.com/agoraproto/agora
> First trade: [BaseScan link]
> Built for agents, not for humans. Agents pay agents in USDC, no
> Stripe, no banks, no KYC. The settlement layer is real today.

(Hold this until the API is updated and a non-self-demo trade has run.
A teaser without working endpoints would be a lie.)

## Sources of truth

- Contract source: [`contracts/src/AgoraEscrow.sol`](../contracts/src/AgoraEscrow.sol)
- Deploy script: [`contracts/script/Deploy.s.sol`](../contracts/script/Deploy.s.sol)
- ADR 009 (why USDC/Base): [`docs/decisions/009-stablecoin-payment-architecture.md`](decisions/009-stablecoin-payment-architecture.md)
- x402 protocol doc: [`docs/x402.md`](x402.md)
- Sprint 9 runbook: [`SEPOLIA_DEPLOY.md`](../SEPOLIA_DEPLOY.md)
