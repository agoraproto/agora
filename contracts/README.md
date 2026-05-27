# Agora Contracts

Solidity contracts for the Agora protocol: USDC escrow with on-chain dispute / refund paths.

## Files

- `src/AgoraEscrow.sol` — V1, currently deployed on Base Sepolia at
  `0xCE783B527C83c4fFFF3D3565c0F3C3204be02B76`. See `SECURITY_REVIEW.md` for
  known limitations; **NOT mainnet-ready** (external audit 2026-05-27).
- `src/AgoraEscrowV2.sol` — V2, addresses the V1 audit findings:
  `Ownable2Step`, `SafeERC20`, `ReentrancyGuard`, `Pausable`, fee-snapshotting,
  `refundExpired`, `resolveDispute`. **In repo, not yet deployed, not yet
  externally audited.**
- `test/` — Foundry tests for both versions.

## Run the tests reproducibly

```bash
cd contracts
git submodule update --init --recursive
forge test
```

The submodules pulled in:

- [forge-std](https://github.com/foundry-rs/forge-std) `v1.9.4` — Foundry's
  testing helpers (`Test.sol`, `console.sol`, …)
- [openzeppelin-contracts](https://github.com/OpenZeppelin/openzeppelin-contracts)
  `v5.0.2` — Used by V2 for `SafeERC20`, `Ownable2Step`, `ReentrancyGuard`,
  `Pausable`.

If you cloned without `--recurse-submodules`, run the `submodule update`
command above; otherwise `forge test` fails with `Source not found:
forge-std/Test.sol`.

## V1 vs V2

See `SECURITY_REVIEW.md` for V1 limitations. The audit roadmap is:

1. Migrate the live API (`apps/backend/.../routes/x402.py`) to V2's ABI
2. Add `Resolved` status (V2 status code 6) handling to the chain watcher
3. Deploy V2 under a Safe multisig + timelock
4. External audit of V2 before any mainnet exposure
