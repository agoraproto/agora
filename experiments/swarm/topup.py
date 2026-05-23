"""Sprint 14 — auto-topup the swarm.

Run every 15 minutes via systemd-timer (agora-topup.timer).

Refills any buyer with USDC < BUYER_MIN_USDC up to BUYER_TARGET_USDC,
drawing from the deployer wallet. Optionally re-balances providers
who accumulated more than PROVIDER_REBALANCE_THRESHOLD by sending
the excess back to the poorest buyers.

Reads the deployer's private key from /opt/agora/experiments/swarm/.deployer-key
(a single hex-encoded private key, no '0x' prefix needed). That file
is gitignored — never commit it.

Idempotent: if no agent needs a top-up, it logs and exits cleanly.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

from eth_account import Account
from web3 import Web3

# ─── Tunables ────────────────────────────────────────────────────────
BUYER_MIN_USDC = 0.60                 # below this, refill
BUYER_TARGET_USDC = 1.50              # refill up to this
PROVIDER_REBALANCE_THRESHOLD = 2.00   # above this, send excess to buyers
PROVIDER_KEEP = 0.10                  # leave this much with the provider
MIN_TRANSFER = 0.10                   # don't send sub-cent moves

USDC_ADDR = Web3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e")
RPC = "https://sepolia.base.org"
HERE = Path(__file__).parent
DATA = HERE / "data"
WALLETS_FILE = DATA / "wallets.json"
DEPLOYER_KEY_FILE = HERE / ".deployer-key"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [topup] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("topup")


# ─── ABIs ────────────────────────────────────────────────────────────
USDC_ABI = [
    {
        "name": "balanceOf", "type": "function", "stateMutability": "view",
        "inputs": [{"name": "a", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "transfer", "type": "function", "stateMutability": "nonpayable",
        "inputs": [{"name": "to", "type": "address"}, {"name": "v", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
]


def usdc_units(amount: float) -> int:
    """Convert a USDC float to smallest unit (6 decimals)."""
    return int(round(amount * 1_000_000))


def main() -> None:
    if not WALLETS_FILE.exists():
        log.error("wallets.json missing — run wallet_setup.py --gen first")
        sys.exit(1)
    if not DEPLOYER_KEY_FILE.exists():
        log.error("deployer key missing — create %s with hex private key", DEPLOYER_KEY_FILE)
        sys.exit(1)

    deployer_key = DEPLOYER_KEY_FILE.read_text().strip()
    if not deployer_key.startswith("0x"):
        deployer_key = "0x" + deployer_key

    wallets = json.loads(WALLETS_FILE.read_text())

    w3 = Web3(Web3.HTTPProvider(RPC))
    deployer = Account.from_key(deployer_key)
    usdc = w3.eth.contract(address=USDC_ADDR, abi=USDC_ABI)
    gas_price = w3.eth.gas_price

    # Snapshot balances in one pass
    balances: dict[str, int] = {}
    for slug, w in wallets.items():
        balances[slug] = usdc.functions.balanceOf(w["address"]).call()
    deployer_bal = usdc.functions.balanceOf(deployer.address).call()
    log.info("deployer balance: %.4f USDC", deployer_bal / 1e6)

    # ─── 1. Topup poor buyers from deployer ──────────────────────
    needs = []
    for slug, w in wallets.items():
        if w["role"] != "buyer":
            continue
        bal = balances[slug]
        if bal < usdc_units(BUYER_MIN_USDC):
            delta = usdc_units(BUYER_TARGET_USDC) - bal
            needs.append((slug, w["address"], delta))

    if not needs:
        log.info("no buyers below %.2f USDC — nothing to top up", BUYER_MIN_USDC)
    else:
        total_needed = sum(d for _, _, d in needs)
        log.info(
            "%d buyer(s) below %.2f USDC; total topup = %.4f USDC",
            len(needs), BUYER_MIN_USDC, total_needed / 1e6,
        )
        if deployer_bal < total_needed:
            log.warning(
                "deployer balance %.4f < required %.4f — proportional topup",
                deployer_bal / 1e6, total_needed / 1e6,
            )

        nonce = w3.eth.get_transaction_count(deployer.address, "pending")
        sent = 0
        for slug, addr, delta in needs:
            if delta < usdc_units(MIN_TRANSFER):
                continue
            try:
                tx = usdc.functions.transfer(
                    Web3.to_checksum_address(addr), delta
                ).build_transaction({
                    "from": deployer.address, "nonce": nonce,
                    "gas": 80000, "gasPrice": gas_price, "chainId": 84532,
                })
                signed = deployer.sign_transaction(tx)
                h = w3.eth.send_raw_transaction(signed.raw_transaction)
                log.info("  → %s +%.4f USDC tx=0x%s",
                         slug, delta / 1e6, h.hex()[:16])
                nonce += 1
                sent += 1
            except Exception as e:
                log.error("  topup %s failed: %s", slug, e)
                break
        log.info("topup phase done: %d tx broadcast", sent)

    # ─── 2. Re-balance rich providers to deployer ───────────────
    # We send back to the deployer (rather than directly to buyers) so
    # the next tick can redistribute fairly. Sometimes providers earn
    # so much that they imbalance the system.
    rich = []
    for slug, w in wallets.items():
        if w["role"] != "provider":
            continue
        bal = balances[slug]
        if bal > usdc_units(PROVIDER_REBALANCE_THRESHOLD):
            keep = usdc_units(PROVIDER_KEEP)
            excess = bal - keep
            if excess >= usdc_units(MIN_TRANSFER):
                rich.append((slug, w, excess))

    if not rich:
        log.info("no providers above %.2f USDC — no rebalance needed", PROVIDER_REBALANCE_THRESHOLD)
    else:
        log.info("rebalancing %d rich provider(s) back to deployer", len(rich))
        for slug, w, excess in rich:
            try:
                acc = Account.from_key(w["private_key"])
                nonce = w3.eth.get_transaction_count(acc.address, "pending")
                tx = usdc.functions.transfer(
                    deployer.address, excess
                ).build_transaction({
                    "from": acc.address, "nonce": nonce,
                    "gas": 80000, "gasPrice": gas_price, "chainId": 84532,
                })
                signed = acc.sign_transaction(tx)
                h = w3.eth.send_raw_transaction(signed.raw_transaction)
                log.info("  ← %s -%.4f USDC tx=0x%s",
                         slug, excess / 1e6, h.hex()[:16])
            except Exception as e:
                log.error("  rebalance %s failed: %s", slug, e)

    log.info("tick complete")


if __name__ == "__main__":
    main()
