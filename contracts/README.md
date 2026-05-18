# Agora Smart Contracts (Foundry)

Solidity-Contracts für Escrow auf USDC/Base. Stage 1: deterministische Code-Disputes (siehe ADR 008). Stage 2+: optimistische Stage-Gates, dann ZK-Verifier.

## Setup

```bash
# Foundry installieren
curl -L https://foundry.paradigm.xyz | bash
foundryup

# Deps
cd contracts
git clone --depth 1 --branch v5.0.2 https://github.com/OpenZeppelin/openzeppelin-contracts.git lib/openzeppelin-contracts
git clone --depth 1 https://github.com/foundry-rs/forge-std.git lib/forge-std
```

## Tests

```bash
forge test -vv
```

## Lokales Deployment (Anvil)

```bash
# In separatem Terminal:
anvil

# Deploy mit Anvil-Default-Key:
forge create src/AgoraEscrow.sol:AgoraEscrow \
  --rpc-url anvil \
  --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
  --constructor-args 0x0000000000000000000000000000000000000001 0x0000000000000000000000000000000000000002 0x0000000000000000000000000000000000000003
```

## Deployment auf Base Sepolia (Testnet)

1. `.env` befüllen (siehe `.env.example`):
   - `PRIVATE_KEY` — fresh key, NICHT wiederverwenden
   - `RPC_URL=https://sepolia.base.org`
   - `USDC_ADDRESS=0x036CbD53842c5426634e7929541eC2318f3dCF7e`
   - `FEE_RECIPIENT` und `INSURANCE_POOL` (kann fürs Testen dieselbe Adresse sein)
   - Optional: `BASESCAN_API_KEY` für Verifikation

2. Sepolia-ETH besorgen (Faucet): https://www.coinbase.com/faucets/base-sepolia-faucet

3. Deploy:
   ```bash
   source .env
   forge script script/Deploy.s.sol:Deploy \
     --rpc-url base_sepolia \
     --broadcast --verify \
     --etherscan-api-key $BASESCAN_API_KEY
   ```

4. Adresse des deployten Contracts in `apps/backend/.env` als `ESCROW_CONTRACT_ADDRESS` eintragen.

## Deployment auf Base Mainnet (Production)

**NUR nach erfolgreichem Sepolia-Test.** Identischer Befehl, aber `--rpc-url base_mainnet`, `USDC_ADDRESS=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`, und Deployer-Wallet muss ~5-10 € ETH auf Base haben.

## Wichtige Hinweise

- **Nicht auditiert.** Vor Mainnet-Deploy mit echtem Volumen: Audit durch OpenZeppelin/Trail of Bits oder Code4rena Public Audit.
- **Owner-Key sichern.** Der Deployer wird `owner` und kann Fees ändern, `feeRecipient`/`insurancePool` swappen, Ownership transferieren. Bei Mainnet: Multisig/Hardware-Wallet, nicht Hot-Wallet.
- **Upgradeability:** Nicht eingebaut. Migration = neuer Contract + Off-Chain-Reroute (akzeptabel im Bootstrap, da Volumen niedrig).
