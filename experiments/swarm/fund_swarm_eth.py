"""Sprint 23 — ETH-Topup für Swarm-Wallets.

Das Sprint-14-USDC-Topup refillt nur Stablecoins. ETH (Gas) ist davon
nicht abgedeckt. Nach Wochen on-chain-Aktivität geraten die mit 0.00005
ETH initialisierten Swarm-Wallets unter den Gas-Schwellwert und können
keine Tx mehr senden — die ganze Swarm bleibt schleichend stehen.

Dieser Script ist die analoge ETH-Variante:
  - Lese alle Wallets aus /opt/agora/experiments/swarm/data/wallets.json
  - Für jede Adresse mit Balance < THRESHOLD: schicke TOPUP_AMOUNT ETH
    vom Deployer
  - Idempotent: über THRESHOLD ⇒ skip
  - Mit --slug X / --addr 0x... gezielt eine einzelne Wallet topuppen

Usage:
  python3 fund_swarm_eth.py                       # alle dünne Wallets
  python3 fund_swarm_eth.py --slug marketing-alice  # nur eine
  python3 fund_swarm_eth.py --apply false           # dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

WALLETS = Path("/opt/agora/experiments/swarm/data/wallets.json")
DEPLOYER_KEY = Path("/opt/agora/experiments/swarm/.deployer-key")
RPC = "https://sepolia.base.org"
THRESHOLD_ETH = Decimal("0.0003")  # below this we top up
TOPUP_ETH = Decimal("0.0005")      # ~250 tx worth of gas
CHAIN_ID = 84532


def load_deployer_key() -> str:
    if not DEPLOYER_KEY.is_file():
        sys.exit(f"missing {DEPLOYER_KEY}")
    k = DEPLOYER_KEY.read_text().strip()
    return k if k.startswith("0x") else "0x" + k


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", help="Only topup this swarm slug (else: all)")
    ap.add_argument("--addr", help="Direct address — overrides --slug, no wallets.json lookup")
    ap.add_argument("--apply", default="true", help="false = dry-run")
    args = ap.parse_args()
    apply = args.apply.lower() not in ("false", "0", "no")

    from eth_account import Account
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 20}))
    deployer = Account.from_key(load_deployer_key())
    dep_bal = Decimal(w3.eth.get_balance(deployer.address)) / Decimal(10**18)
    print(f"=== Deployer: {deployer.address}  balance: {dep_bal} ETH ===\n")

    # Build the target list
    if args.addr:
        targets = [{"slug": "(custom)", "address": args.addr}]
    else:
        if not WALLETS.is_file():
            sys.exit(f"missing {WALLETS}")
        wallets = json.loads(WALLETS.read_text())
        if args.slug:
            if args.slug not in wallets:
                sys.exit(f"slug {args.slug} not in wallets.json")
            targets = [{"slug": args.slug, "address": wallets[args.slug]["address"]}]
        else:
            targets = [{"slug": s, "address": w["address"]} for s, w in wallets.items()]

    # Survey balances + plan
    plan = []
    for t in targets:
        bal_wei = w3.eth.get_balance(Web3.to_checksum_address(t["address"]))
        bal_eth = Decimal(bal_wei) / Decimal(10**18)
        needs_topup = bal_eth < THRESHOLD_ETH
        plan.append({**t, "balance_eth": bal_eth, "needs_topup": needs_topup})
        marker = "→" if needs_topup else "✓"
        print(f"  {marker} {t['slug']:25s} {t['address']}  {bal_eth} ETH  "
              f"{'(needs topup)' if needs_topup else '(skip)'}")

    todo = [p for p in plan if p["needs_topup"]]
    if not todo:
        print("\nNothing to do — all wallets above threshold.")
        return

    # Sanity-check deployer has enough budget
    needed = TOPUP_ETH * len(todo) + Decimal("0.0001")  # incl. gas
    if dep_bal < needed:
        print(f"\n⚠  Deployer has {dep_bal} ETH but {len(todo)} top-ups need {needed} ETH.")
        print("   Refill the deployer first, or use --slug to do just one.")
        return

    if not apply:
        print(f"\n[dry-run] would top up {len(todo)} wallet(s) with {TOPUP_ETH} ETH each.")
        return

    # Execute
    print(f"\n=== Sending {TOPUP_ETH} ETH to {len(todo)} wallet(s) ===\n")
    nonce = w3.eth.get_transaction_count(deployer.address, "pending")
    gas_price = w3.eth.gas_price
    for p in todo:
        tx = {
            "to": Web3.to_checksum_address(p["address"]),
            "value": int(TOPUP_ETH * Decimal(10**18)),
            "gas": 21000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        }
        signed = deployer.sign_transaction(tx)
        try:
            h = w3.eth.send_raw_transaction(signed.raw_transaction)
            tx_hash = h.hex() if h.hex().startswith("0x") else "0x" + h.hex()
            print(f"  ✓ {p['slug']:25s} {p['address']}  tx={tx_hash}")
            nonce += 1
            time.sleep(0.5)  # small spacing for RPC happiness
        except Exception as e:
            print(f"  ✗ {p['slug']:25s} {p['address']}  failed: {e}")

    print(f"\nDone. Sent {len(todo)} × {TOPUP_ETH} ETH. View on basescan-sepolia.")


if __name__ == "__main__":
    main()
