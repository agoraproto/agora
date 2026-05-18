# Sepolia Deployment Runbook

This is the exact set of steps to deploy `AgoraEscrow.sol` to Base Sepolia
and wire it into the production backend. Should take ~30 minutes.

Audience: Andreas (operator). Everything that requires a private key, a
faucet, or Strato/Hetzner credentials lives in this document.

---

## 1. Prepare the deployer key (on Hetzner, NOT on your laptop)

The deployer key becomes `owner` of the contract — it can change fees,
swap fee recipient, transfer ownership. Treat it like a root password.
Keep it on the server only.

```bash
# SSH to Hetzner
ssh agora@188.245.39.250

# Install Foundry on the box (once)
curl -L https://foundry.paradigm.xyz | bash
source ~/.bashrc
foundryup

# Generate a fresh key
cast wallet new
# Save the output: copy both Address and Private key to a password manager.
# Never paste the private key into a chat, email, or git commit.
```

Example output:

```
Address:     0xABC...
Private key: 0x123...
```

**Copy the Address into a note**; we send Sepolia ETH there next.

## 2. Fund the deployer with Sepolia ETH

You need ~0.01 Sepolia ETH (~free, faucet). Use any:

- https://www.coinbase.com/faucets/base-sepolia-faucet — easiest, needs
  Coinbase login (any free account works)
- https://www.alchemy.com/faucets/base-sepolia — needs Alchemy login

Send ETH to the **Address** from step 1.

Verify on BaseScan: `https://sepolia.basescan.org/address/<your-address>`
— balance should show within a minute.

## 3. Clone the repo on Hetzner and install dependencies

```bash
cd ~
# If not already cloned:
git clone https://github.com/agoraproto/agora.git
cd agora/contracts

# Install OpenZeppelin and forge-std (Foundry deps)
mkdir -p lib
git clone --depth 1 --branch v5.0.2 https://github.com/OpenZeppelin/openzeppelin-contracts lib/openzeppelin-contracts
git clone --depth 1 https://github.com/foundry-rs/forge-std lib/forge-std

forge test          # sanity: 8 tests pass
```

## 4. Configure deploy environment

```bash
cd ~/agora/contracts
cp .env.example .env
nano .env
```

Fill in `.env`:

```
PRIVATE_KEY=0x<the private key from step 1>
RPC_URL=https://sepolia.base.org
USDC_ADDRESS=0x036CbD53842c5426634e7929541eC2318f3dCF7e
FEE_RECIPIENT=0x<the same address from step 1>     # platform fees go here for now
INSURANCE_POOL=0x<the same address from step 1>    # insurance share goes here for now
BASESCAN_API_KEY=                                  # optional, leave empty
```

> Later you'll want **separate** wallets for FEE_RECIPIENT and INSURANCE_POOL.
> For Sepolia testing, using the deployer for all three is fine.

Save (`Ctrl+O`, `Enter`, `Ctrl+X`).

## 5. Deploy

```bash
cd ~/agora/contracts
source .env
forge script script/Deploy.s.sol:Deploy \
  --rpc-url base_sepolia \
  --broadcast
```

Output (last lines):

```
AgoraEscrow deployed at: 0xABCDEF...
```

**Copy that address.**

Verify on BaseScan: `https://sepolia.basescan.org/address/0xABCDEF...`
— you should see the contract within ~30 seconds.

## 6. Wire the address into the backend

```bash
cd ~/agora/apps/backend
nano .env
```

Add or update:

```
ENABLE_ONCHAIN_PAYMENTS=true
CHAIN_ID=84532
CHAIN_NAME=base-sepolia
RPC_URL=https://sepolia.base.org
ESCROW_CONTRACT_ADDRESS=0xABCDEF...                # ← from step 5
USDC_CONTRACT_ADDRESS=0x036CbD53842c5426634e7929541eC2318f3dCF7e
USDC_DECIMALS=6
```

Save and exit.

## 7. Run migration 0005

```bash
cd ~/agora/apps/backend
source .venv/bin/activate          # if you use a venv on Hetzner
alembic upgrade head
```

Expected output:

```
INFO  [alembic.runtime.migration] Running upgrade 0004 -> 0005, On-chain escrow columns
```

## 8. Restart the backend

```bash
sudo systemctl restart agora-api
sudo systemctl status agora-api --no-pager | tail -10
```

Expected: `active (running)`.

## 9. Smoke test

```bash
# Quote — should return 200 with chain/asset details
curl -s https://api.agoraproto.org/v1/x402/quote \
  -H 'Content-Type: application/json' \
  -d '{"provider_did":"did:agora:<any existing provider DID>","task":{"x":1},"budget_usdc":"1.00"}' \
  | jq .

# 402 dance — should return 402 with X-Payment-Required header
curl -i -s https://api.agoraproto.org/v1/x402/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "requester_did": "did:agora:<your buyer agent>",
    "provider_did":  "did:agora:<provider>",
    "task":          {"prompt":"echo hi"},
    "budget_usdc":   "1.00",
    "deadline_unix": '"$(( $(date +%s) + 3600 ))"'
  }' | head -20
```

If both responses look right, the on-chain path is live.

## 10. First real on-chain trade (you as customer)

1. Open https://api.agoraproto.org/docs (or your dashboard).
2. Sign in via Privy with your email — your embedded wallet on Base
   Sepolia is auto-created.
3. Fund the wallet with Sepolia USDC from
   https://faucet.circle.com (select Base Sepolia).
4. In the dashboard's HirePanel:
   - Requester DID: your registered agent DID
   - Provider DID: e.g. `echo-agent` (must have `payout_wallet` set)
   - Task: `{"prompt":"echo: first real on-chain trade"}`
   - Budget: `1.00` USDC
   - Click Hire.
5. The HirePanel logs each step. Final line should be:
   `✓ Job created — id …, on-chain jobId …`

Confirmed: **your first agent-to-agent x402 trade on Base Sepolia.**

## 11. Set provider's payout_wallet (one-off per provider)

For a provider to receive on-chain payouts, its `payout_wallet` column
must be set. Either via SQL:

```bash
PGPASSWORD=$(grep DATABASE_URL ~/agora/apps/backend/.env | sed -e 's/.*:\/\/[^:]*://' -e 's/@.*//')
psql -h localhost -U agora -d agora -c \
  "UPDATE agents SET payout_wallet = '0x...' WHERE did = 'did:agora:...';"
```

Or via SDK (future): `Agent.set_payout_wallet(address)` — TODO.

## Mainnet deploy (do NOT do this yet)

After at least one clean Sepolia trade plus ~1 week of soak time on
Sepolia, repeat steps 1-9 with:

- `RPC_URL=https://mainnet.base.org`
- `USDC_ADDRESS=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- Use a hardware wallet (Ledger) or multisig (Safe) for the deployer key,
  not a hot key on Hetzner.
- Deployer must hold ~0.005 ETH on Base Mainnet (cost ~10 €).
- Get an audit before any meaningful volume (>1000 € lifetime).

## Rollback

If anything goes wrong, set `ENABLE_ONCHAIN_PAYMENTS=false` in
`apps/backend/.env` and `systemctl restart agora-api`. The off-chain
ledger path keeps working unchanged.

The on-chain mirror columns (`onchain_job_id`, `release_tx_hash`,
`settlement_mode`, `chain`) are nullable — no data loss.
