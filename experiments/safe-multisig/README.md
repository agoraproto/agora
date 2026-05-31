# experiments/safe-multisig

V2 escrow ownership lives in a 2-of-2 Gnosis Safe on Base Sepolia
(`0x8Ec63Fe30DAb84308B5009b8D91d9E4dEB5a61FC`) as of Sprint 37
(2026-05-31). This folder holds the operational scripts.

## Scripts

| File | Purpose | Sprint |
|---|---|---|
| `01-deploy.sh` | Generate 2 cosigner keys, deploy 2-of-2 Safe via official ProxyFactory, initiate `V2.transferOwnership(safe)` | 37a + 37b |
| `02-accept-ownership.sh` | Build the SafeTx for `V2.acceptOwnership()`, EIP-712 sign with both cosigners, broadcast `Safe.execTransaction` | 37c |
| `03-diagnose.sh` | Read live V2 + Safe state + decode receipt logs — used when 37c initially looked like it had failed (turned out to be RPC stale read) | 37c-fix |
| `admin-op-template.sh` | **Reusable template** for ANY Safe-admin operation on V2 or other targets. Edit the `CALLDATA` line; default `DRY_RUN=1` previews without broadcasting | 37e |

## Cosigner keys (server only)

The two cosigner private keys live on `agora-1` under
`/opt/agora/experiments/safe-multisig/.cosigner-1` and `.cosigner-2`
(mode 600, not in this repo). For Mainnet they must be swapped via
the Safe UI's `addOwner` + `removeOwner` flow for hardware wallets
or other secure devices.

## How to add Safe owners (e.g. before Mainnet)

Use `admin-op-template.sh` with the Safe as TARGET:

```bash
TARGET=0x8Ec63Fe30DAb84308B5009b8D91d9E4dEB5a61FC   # the Safe itself
# Add a new owner and bump threshold to 2 of 3:
CALLDATA=$($CAST calldata "addOwnerWithThreshold(address,uint256)" 0xYOUR_HW_WALLET 2)
```

Then a follow-up call to remove the test cosigner:

```bash
# Remove cosigner #1, keep threshold at 2:
#   prevOwner is the linked-list predecessor of the owner being removed.
#   The Safe's owner-linked-list head is the sentinel 0x...0001.
CALLDATA=$($CAST calldata "removeOwner(address,address,uint256)" 0xPREV 0xCOSIGNER_TO_REMOVE 2)
```

## Open hardening items

- **Timelock between Safe and V2** (Sprint 38 candidate). Currently every
  Safe-signed admin op executes immediately. A `TimelockController`
  layer would give 24 h to react to a malicious proposal.
- **Hardware-wallet cosigners** must replace the test cosigners before
  Mainnet — the test cosigner private keys are stored on a single
  server, which is fine for testnet practice but unacceptable for
  Mainnet.
