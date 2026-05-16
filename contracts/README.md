# Agora Smart Contracts (Foundry)

Solidity-Contracts für Escrow, Payments und (später) Reputation/Disputes.

## Setup

```bash
# Foundry installieren (https://book.getfoundry.sh/getting-started/installation)
curl -L https://foundry.paradigm.xyz | bash
foundryup

# OpenZeppelin als lib
cd contracts
forge install OpenZeppelin/openzeppelin-contracts --no-commit
forge install foundry-rs/forge-std --no-commit
```

## Tests

```bash
forge test -vv
```

## Lokales Deployment (Anvil)

```bash
# Aus repo-root: Anvil läuft via Docker Compose
docker compose up -d anvil

# Deploy
forge create src/AgoraEscrow.sol:AgoraEscrow \
  --rpc-url anvil \
  --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
  --constructor-args 0x0000000000000000000000000000000000000001 0x0000000000000000000000000000000000000002
```

## Wichtige Hinweise

- **Diese Contracts sind nicht auditiert.** Nicht produktiv einsetzen.
- Vor Mainnet: Audit durch OpenZeppelin oder Trail of Bits + Code4rena Public Audit (siehe Review §3.6).
- Upgradeability-Pattern (UUPS oder Transparent Proxy) noch nicht implementiert.
- Dispute-State ist Stub – Stage-1/2/3-Logik (Spec §6.7) folgt off-chain.
