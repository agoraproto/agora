"""Sprint 20c — fix-up: fund audit agent wallet from deployer + refresh listing.json.

Run once on the server. Performs two independent fix-ups so Sprint 20
ends in a runnable state:

  1. Sends 0.001 ETH from the deployer wallet
     (/opt/agora/experiments/swarm/.deployer-key) to the audit agent's
     EVM address, so submitResult tx's have gas. Skips if balance > 0.0005.
  2. Refetches the current active listing for the audit agent's DID
     from the API and overwrites data/listing.json with the result, so
     register.py's idempotency check sees the right ID.

Usage:
  /opt/agora/apps/backend/.venv/bin/python3 fund_wallet.py
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
CREDS = DATA / "credentials.json"
LISTING = DATA / "listing.json"

API = os.environ.get("AGORA_API", "https://api.agoraproto.org")
RPC = os.environ.get("AGORA_RPC", "https://sepolia.base.org")
DEPLOYER_KEY_PATHS = [
    "/opt/agora/experiments/swarm/.deployer-key",
    str(HERE.parent / "swarm" / ".deployer-key"),
]
TOPUP_ETH = Decimal("0.001")
MIN_BALANCE_ETH = Decimal("0.0005")  # only top up if balance falls below


def load_creds() -> dict:
    if not CREDS.is_file():
        sys.exit(f"missing {CREDS} — run register.py first")
    return json.loads(CREDS.read_text())


def find_deployer_key() -> str:
    for p in DEPLOYER_KEY_PATHS:
        if os.path.isfile(p):
            k = open(p).read().strip()
            return k if k.startswith("0x") else "0x" + k
    sys.exit(f"deployer key not found in: {DEPLOYER_KEY_PATHS}")


def fund_wallet(target: str) -> None:
    from eth_account import Account
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        sys.exit(f"RPC {RPC} not reachable")

    target_cs = Web3.to_checksum_address(target)
    balance_wei = w3.eth.get_balance(target_cs)
    balance_eth = Decimal(balance_wei) / Decimal(10**18)
    print(f"  current balance: {balance_eth} ETH")
    if balance_eth >= MIN_BALANCE_ETH:
        print(f"  ✓ balance >= {MIN_BALANCE_ETH} ETH — skipping top-up")
        return

    key = find_deployer_key()
    deployer = Account.from_key(key)
    print(f"  deployer: {deployer.address}")
    dep_bal = Decimal(w3.eth.get_balance(deployer.address)) / Decimal(10**18)
    print(f"  deployer balance: {dep_bal} ETH")

    nonce = w3.eth.get_transaction_count(deployer.address, "pending")
    gas_price = w3.eth.gas_price
    amount_wei = int(TOPUP_ETH * Decimal(10**18))
    tx = {
        "to": target_cs,
        "value": amount_wei,
        "gas": 21000,
        "gasPrice": gas_price,
        "nonce": nonce,
        "chainId": 84532,
    }
    signed = deployer.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    tx_hash = "0x" + h.hex() if not h.hex().startswith("0x") else h.hex()
    print(f"  sent {TOPUP_ETH} ETH → {target_cs}")
    print(f"  tx: https://sepolia.basescan.org/tx/{tx_hash}")
    # Don't wait for receipt — confirmation lands within ~2s typically.


def refresh_listing(did: str) -> None:
    import httpx

    r = httpx.get(
        f"{API}/v1/listings",
        params={"seller_did": did, "service_capability": "AuditDocumentGapCheck"},
        timeout=15,
    )
    if r.status_code != 200:
        print(f"  ✗ listing lookup failed: {r.status_code} {r.text[:200]}")
        return
    listings = r.json().get("listings", [])
    active = [l for l in listings if l.get("status") == "active"]
    if not active:
        print(f"  ✗ no active listing for {did}")
        return
    # Pick the lowest-priced active listing (current house rule: 0.01 USDC)
    chosen = min(active, key=lambda l: Decimal(l.get("price_amount", "999")))
    DATA.mkdir(parents=True, exist_ok=True)
    LISTING.write_text(json.dumps(chosen, indent=2))
    print(f"  ✓ listing.json refreshed → {chosen['id']} "
          f"({chosen['price_amount']} {chosen['price_currency']})")


def main() -> None:
    creds = load_creds()
    addr = creds["evm_address"]
    did = creds["did"]
    print(f"=== Audit agent: {did} ===")
    print(f"=== Wallet: {addr} ===")

    print("\n[1/2] Funding wallet with ETH for gas")
    try:
        fund_wallet(addr)
    except Exception as e:
        print(f"  ✗ funding failed: {e}")

    print("\n[2/2] Refreshing listing.json")
    try:
        refresh_listing(did)
    except Exception as e:
        print(f"  ✗ refresh failed: {e}")

    print("\nDone. The audit agent will pick up new jobs on its next poll cycle.")


if __name__ == "__main__":
    main()
