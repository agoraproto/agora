"""Swarm orchestrator — runs all 20 agents concurrently as asyncio tasks.

Usage:
  python3 orchestrator.py            # run forever
  python3 orchestrator.py --limit 5  # stop after 5 minutes (demo mode)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents.buyer import Buyer
from agents.provider import Provider

WALLETS_FILE = Path(__file__).parent / "data" / "wallets.json"
DIDS_FILE = Path(__file__).parent / "data" / "dids.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("swarm.orchestrator")


async def main(limit_minutes: float | None = None) -> None:
    if not WALLETS_FILE.exists() or not DIDS_FILE.exists():
        sys.exit("Run wallet_setup.py --gen + register_agents.py first.")
    wallets = json.loads(WALLETS_FILE.read_text())
    dids = json.loads(DIDS_FILE.read_text())

    tasks: list[asyncio.Task] = []
    for slug, w in wallets.items():
        did = dids.get(slug)
        if not did:
            log.warning("no DID for %s — skipping", slug)
            continue
        if w["role"] == "provider":
            agent = Provider(slug, did, w["address"], w["private_key"])
        else:
            agent = Buyer(slug, did, w["address"], w["private_key"])
        tasks.append(asyncio.create_task(agent.run(), name=slug))

    log.info("started %d agents", len(tasks))
    if limit_minutes:
        log.info("running for %.1f minutes then shutting down", limit_minutes)
        await asyncio.sleep(limit_minutes * 60)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        log.info("shutdown complete")
    else:
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=float, default=None, help="Stop after N minutes (demo mode)")
    args = ap.parse_args()
    try:
        asyncio.run(main(args.limit))
    except KeyboardInterrupt:
        log.info("interrupted — bye")
