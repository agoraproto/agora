"""Generate 20 fresh EVM wallets for the swarm (Sprint 11).

Deterministic per slug — so re-running this script returns the same
addresses. Each agent gets a key derived from
SHA256(MASTER_SEED || slug)[:32]. The master seed is read from the
environment variable `AGORA_SWARM_MASTER_SEED` (or generated and saved
into ./data/master_seed.txt on first run).

Outputs:
  data/wallets.json   — { slug: {address, private_key} } for all 20.

Funding (separate step):
  python3 wallet_setup.py --fund
  → reads wallets.json, sends ETH + USDC from the deployer wallet
    (key in env DEPLOYER_PRIVATE_KEY) to each agent according to its
    spec (Buyer initial_usdc, all 0.0005 ETH).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from decimal import Decimal
from pathlib import Path

# Make `personalities` importable when called as a script.
sys.path.insert(0, str(Path(__file__).parent))

from eth_account import Account
from web3 import Web3

from personalities import BUYERS, PROVIDERS

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
SEED_FILE = DATA_DIR / "master_seed.txt"
WALLETS_FILE = DATA_DIR / "wallets.json"

RPC = "https://sepolia.base.org"
USDC_ADDR = Web3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e")
PER_AGENT_ETH_WEI = int(0.0005 * 10**18)   # 0.0005 ETH gas budget


def get_master_seed() -> bytes:
    env = os.environ.get("AGORA_SWARM_MASTER_SEED")
    if env:
        return bytes.fromhex(env.replace("0x", ""))
    if SEED_FILE.exists():
        return bytes.fromhex(SEED_FILE.read_text().strip().replace("0x", ""))
    seed = secrets.token_bytes(32)
    SEED_FILE.write_text(seed.hex())
    print(f"Generated new master seed → {SEED_FILE}")
    return seed


def derive_key(master: bytes, slug: str) -> str:
    raw = hashlib.sha256(master + slug.encode()).digest()
    return "0x" + raw.hex()


def gen_all() -> dict[str, dict[str, str]]:
    master = get_master_seed()
    wallets: dict[str, dict[str, str]] = {}
    for spec in PROVIDERS:
        key = derive_key(master, spec.slug)
        acc = Account.from_key(key)
        wallets[spec.slug] = {
            "role": "provider",
            "address": acc.address,
            "private_key": key,
        }
    for spec in BUYERS:
        key = derive_key(master, spec.slug)
        acc = Account.from_key(key)
        wallets[spec.slug] = {
            "role": "buyer",
            "address": acc.address,
            "private_key": key,
        }
    return wallets


def cmd_gen() -> None:
    wallets = gen_all()
    WALLETS_FILE.write_text(json.dumps(wallets, indent=2))
    print(f"Wrote {len(wallets)} wallets → {WALLETS_FILE}")
    for slug, w in wallets.items():
        print(f"  {slug:25s} {w['role']:8s} {w['address']}")


def cmd_show() -> None:
    if not WALLETS_FILE.exists():
        print("No wallets generated yet — run with --gen first.")
        return
    data = json.loads(WALLETS_FILE.read_text())
    for slug, w in data.items():
        print(f"{slug:25s} {w['role']:8s} {w['address']}")


# ── Funding ─────────────────────────────────────────────────────────


def cmd_fund(dry_run: bool = False) -> None:
    deployer_key = os.environ.get("DEPLOYER_PRIVATE_KEY")
    if not deployer_key:
        sys.exit("DEPLOYER_PRIVATE_KEY env var is required for --fund")
    if not WALLETS_FILE.exists():
        sys.exit("Wallets file missing — run --gen first.")
    wallets = json.loads(WALLETS_FILE.read_text())

    w3 = Web3(Web3.HTTPProvider(RPC))
    deployer = Account.from_key(deployer_key)
    print(f"Deployer: {deployer.address}")

    # Check balances first
    deployer_eth = w3.eth.get_balance(deployer.address)
    usdc = w3.eth.contract(
        address=USDC_ADDR,
        abi=[
            {
                "name": "balanceOf",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "account", "type": "address"}],
                "outputs": [{"name": "", "type": "uint256"}],
            },
            {
                "name": "transfer",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                ],
                "outputs": [{"name": "", "type": "bool"}],
            },
        ],
    )
    deployer_usdc = usdc.functions.balanceOf(deployer.address).call()

    # Build a target balance map per agent
    buyer_usdc = {b.slug: int(b.initial_usdc * 10**6) for b in BUYERS}
    provider_usdc = {p.slug: 0 for p in PROVIDERS}  # providers earn
    target_usdc = {**buyer_usdc, **provider_usdc}

    total_eth_needed = PER_AGENT_ETH_WEI * len(wallets)
    total_usdc_needed = sum(target_usdc.values())

    print(f"Deployer  ETH: {deployer_eth/1e18:.6f} | needs ≥ {total_eth_needed/1e18:.6f}")
    print(f"Deployer USDC: {deployer_usdc/1e6:.6f} | needs ≥ {total_usdc_needed/1e6:.6f}")
    if deployer_eth < total_eth_needed:
        sys.exit("Insufficient ETH on deployer; top up via Alchemy Sepolia faucet")
    if deployer_usdc < total_usdc_needed:
        sys.exit("Insufficient USDC on deployer; top up via faucet.circle.com")
    if dry_run:
        print("Dry-run only. Pass --execute to actually broadcast.")
        return

    gas_price = w3.eth.gas_price
    print(f"Gas price: {gas_price/1e9:.6f} gwei\n")

    # Send ETH first to every agent (no gas needed on receiver yet).
    nonce = w3.eth.get_transaction_count(deployer.address, "pending")
    for slug, w in wallets.items():
        tx = {
            "to": w["address"],
            "value": PER_AGENT_ETH_WEI,
            "gas": 21000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": 84532,
        }
        signed = deployer.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  ETH → {slug:25s} ({w['address']}) tx=0x{h.hex()[:18]}…")
        nonce += 1

    # Then USDC for buyers only.
    for slug, w in wallets.items():
        amt = target_usdc.get(slug, 0)
        if amt == 0:
            continue
        tx = usdc.functions.transfer(w["address"], amt).build_transaction({
            "from": deployer.address,
            "nonce": nonce,
            "gas": 80000,
            "gasPrice": gas_price,
            "chainId": 84532,
        })
        signed = deployer.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  USDC ({amt/1e6:.2f}) → {slug:25s} tx=0x{h.hex()[:18]}…")
        nonce += 1

    print("\nAll funding tx broadcast. Waiting 15s for confirmations…")
    time.sleep(15)
    print("Done — verify with: python3 wallet_setup.py --verify")


def cmd_verify() -> None:
    if not WALLETS_FILE.exists():
        sys.exit("No wallets yet.")
    w3 = Web3(Web3.HTTPProvider(RPC))
    usdc = w3.eth.contract(
        address=USDC_ADDR,
        abi=[
            {
                "name": "balanceOf",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "account", "type": "address"}],
                "outputs": [{"name": "", "type": "uint256"}],
            }
        ],
    )
    wallets = json.loads(WALLETS_FILE.read_text())
    print(f"{'slug':25s} {'role':9s} {'address':44s} {'ETH':>10s} {'USDC':>10s}")
    for slug, w in wallets.items():
        eth = w3.eth.get_balance(w["address"]) / 1e18
        bal = usdc.functions.balanceOf(w["address"]).call() / 1e6
        print(f"{slug:25s} {w['role']:9s} {w['address']:44s} {eth:>10.6f} {bal:>10.4f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", action="store_true", help="Generate the 20 wallets deterministically")
    ap.add_argument("--show", action="store_true", help="Show generated wallets")
    ap.add_argument("--fund", action="store_true", help="Send ETH+USDC from deployer to all agents")
    ap.add_argument("--dry-run", action="store_true", help="With --fund: show plan but don't broadcast")
    ap.add_argument("--verify", action="store_true", help="Read current on-chain balances of all agents")
    args = ap.parse_args()
    if args.gen:
        cmd_gen()
    elif args.show:
        cmd_show()
    elif args.fund:
        cmd_fund(dry_run=args.dry_run)
    elif args.verify:
        cmd_verify()
    else:
        ap.print_help()
