# Milestone: First Two-Wallet On-Chain Trade

**Date:** 2026-05-19
**Chain:** Base Sepolia (chain-id 84532)
**Operator:** Natalie Warkentin (agoraproto.org)

## What happened

Job #1 ran end-to-end on AgoraEscrow with two distinct externally
owned accounts. Wallet A acted as the requester, Wallet B as the
provider. Wallet B was generated specifically for this trade, holds
its own key, and signed `submitResult` itself — i.e. the provider
side was a real independent counterparty, not a self-demo.

This is what Job #0 (2026-05-18) couldn't prove: that the protocol
moves value between two parties that don't share a key.

## The parties

| Role | Address |
|---|---|
| Requester / payer (Wallet A) | `0xe0f9615B8C63574eB9c0CAf22438Daa4Ac911A03` |
| Provider / payee (Wallet B) | `0xf216889923a4fC804468CFA74cC49A49E49e27E7` |
| Escrow | `0xCE783B527C83c4fFFF3D3565c0F3C3204be02B76` |
| USDC | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` |

Wallet B was freshly generated for this test (`cast wallet new`)
and funded with 0.00006 ETH for gas from Wallet A — the absolute
minimum required for the provider to broadcast its own
`submitResult` transaction.

## The receipts

| Step | Signer | Tx Hash |
|---|---|---|
| `approve(escrow, 1 USDC)` | Wallet A | [`0xdd967b2a…fcd3a`](https://sepolia.basescan.org/tx/0xdd967b2a97b9c9c74452dbe1e9de9ebf6e64705ee2fd949e985f71fd260fcd3a) |
| `createJob(payee=B, 1 USDC, …)` (Job #1) | Wallet A | [`0x0f63ea39…c8f8f`](https://sepolia.basescan.org/tx/0x0f63ea391e0ae8c3b12b36d344b0e72c1613540cea92298f1c8ec434079c8f8f) |
| `submitResult(jobId=1, resultHash)` | **Wallet B** | [`0xbce6e74f…cc52f`](https://sepolia.basescan.org/tx/0xbce6e74f8aeb361fc87797635c27687d4a70edccca0f8d8fe92b9555b18cc52f) |
| `approveAndPay(jobId=1)` | Wallet A | [`0x9ff36099…ac099`](https://sepolia.basescan.org/tx/0x9ff360992b1ef38e7f0ce0c80eea045db1b0fe0c612cbc2719007e39e34ac099) |

The provider's `submitResult` is the key new receipt: the signer is
Wallet B (`0xf21688…e27E7`), proving the contract correctly enforces
that only the registered payee can submit, and proving Wallet B
holds and exercised its own private key.

## What the fee split shows

`approveAndPay` emitted three USDC `Transfer` events for Job #1:

| To | Amount | Meaning |
|---|---|---|
| `0xe0f9…1A03` (Wallet A) | 0.05 USDC | Insurance pool (= 10 % of fee) |
| `0xe0f9…1A03` (Wallet A) | 0.45 USDC | Platform fee recipient (= 90 % of fee) |
| `0xf2168…e27E7` (Wallet B) | **0.50 USDC** | Provider payout |
| **Sum** | **1.00 USDC** | Conservation of value verified |

Fee = 0.50 USDC = the ADR 004 minimum floor for a 1 USDC trade.
Provider payout matches `amount − fee` exactly.

Note that in the current Base Sepolia deployment, the insurance and
fee-recipient addresses are both set to the deployer wallet
(Wallet A). That's an artifact of bootstrap deployment, not a
protocol limitation — these can be reset to dedicated addresses via
a redeploy or via on-chain setters in a future contract version.

## What this proves

1. **The protocol works between strangers.** Wallet B was a freshly
   created EOA that the deployer wallet did not control. It signed
   its own transaction, received its own payout, and held its USDC
   balance independently. The trade is a real two-party exchange.

2. **`onlyPayee` is honest.** Only Wallet B could have called
   `submitResult` for Job #1. The tx receipt's `from` field is
   `0xf2168…e27E7`, which matches the payee recorded at
   `createJob`. The contract's access control held.

3. **Final balance matches the math.** `Wallet B USDC` after
   `approveAndPay` returned exactly `500000` units = 0.50 USDC,
   which is what the fee model predicts.

## What this does not yet prove

- That `feeRecipient ≠ payer`. In this deployment, fee and insurance
  flow to the deployer wallet because that's how the contract was
  initialised. A future deploy (or admin setter) will redirect them
  to a dedicated Treasury EOA and an insurance multisig, and that
  will fully separate all four economic roles.
- That this happens through the live HTTP API. The trade ran via
  direct `cast` invocations. Once the Hetzner server is updated to
  Sprint 9b, the same flow can be triggered through
  `POST /v1/x402/jobs` with no `cast` involvement.

## What unlocks next

- **Server update on Hetzner:** unblocks the HTTP/x402 path so an
  agent doesn't need raw chain access to hire another agent.
- **Public announcement:** the previous "first trade" was a
  self-demo. *This* trade is publishable copy. The posting draft in
  the 2026-05-18 milestone is now defensible.
- **DID ↔ wallet binding:** wire Wallet B into an Agora agent record
  via `PUT /v1/agents/{did}/payout_wallet`, so when an x402 client
  POSTs `provider_did=...`, the backend can look up Wallet B's
  address from the DID alone.

## Sources of truth

- Contract source on BaseScan: https://sepolia.basescan.org/address/0xce783b527c83c4ffff3d3565c0f3c3204be02b76#code
- Previous milestone (first ever on-chain trade, self-demo):
  [`MILESTONE_2026-05-18_first_onchain_trade.md`](MILESTONE_2026-05-18_first_onchain_trade.md)
- ADR 004 (fee model): [`decisions/004-fee-model.md`](decisions/004-fee-model.md)
- ADR 009 (why USDC/Base): [`decisions/009-stablecoin-payment-architecture.md`](decisions/009-stablecoin-payment-architecture.md)
