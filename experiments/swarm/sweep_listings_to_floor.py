"""Sprint 22 — sweep all swarm-agent listings down to the 0.01 USDC floor.

House rule (CLAUDE.md): every Agora listing is <= 0.01 USDC, because
Agora is a micro-transaction marketplace between AI agents. The 20-
agent swarm was set up in Sprint 11 with 0.50-0.90 USDC listings —
legacy from before the rule. This script archives each swarm listing
and re-publishes it identically except for the price.

Scope: ONLY listings whose seller_did starts with 'did:agora:swarm-'.
Everything else (external Claude tester listings, user listings, the
two newer compliance agents) is left untouched.

Idempotent: if a listing is already at <= 0.01 USDC, it's skipped.

Usage:
  python3 sweep_listings_to_floor.py            # dry-run by default
  python3 sweep_listings_to_floor.py --apply    # actually do it
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal

import httpx

API = "https://api.agoraproto.org"
FLOOR_PRICE = Decimal("0.01")
SWARM_PREFIX = "did:agora:swarm-"
TIMEOUT = 30


def list_swarm_listings() -> list[dict]:
    """Fetch every active listing belonging to a swarm agent."""
    out: list[dict] = []
    offset = 0
    limit = 100
    with httpx.Client(timeout=TIMEOUT) as client:
        while True:
            r = client.get(f"{API}/v1/listings", params={"limit": limit, "offset": offset})
            r.raise_for_status()
            body = r.json()
            listings = body.get("listings", [])
            if not listings:
                break
            for l in listings:
                if l.get("status") != "active":
                    continue
                if not (l.get("seller_did", "")).startswith(SWARM_PREFIX):
                    continue
                out.append(l)
            offset += len(listings)
            if offset >= body.get("total", 0):
                break
    return out


def archive_listing(client: httpx.Client, lid: str) -> None:
    r = client.delete(f"{API}/v1/listings/{lid}")
    if r.status_code not in (200, 204):
        raise RuntimeError(f"archive {lid} failed: {r.status_code} {r.text[:200]}")


def recreate_listing(client: httpx.Client, original: dict) -> dict:
    """Re-publish a listing with the same content but FLOOR_PRICE."""
    body = {
        "seller_kind": original.get("seller_kind", "agent"),
        "seller_did": original["seller_did"],
        "payout_wallet": original["payout_wallet"],
        "listing_type": original["listing_type"],
        "title": original["title"],
        "description": original["description"],
        "category": original.get("category"),
        "tags": original.get("tags", []),
        "price_amount": str(FLOOR_PRICE),
        "price_currency": original.get("price_currency", "USDC"),
        "service_capability": original.get("service_capability"),
        "service_input_schema": original.get("service_input_schema"),
        "digital_content_type": original.get("digital_content_type"),
        "cover_image_url": original.get("cover_image_url"),
        "images": original.get("images", []),
    }
    # Drop fields the API will reject if they're None on a service listing
    body = {k: v for k, v in body.items() if v is not None}
    r = client.post(f"{API}/v1/listings", json=body)
    if r.status_code != 201:
        raise RuntimeError(f"recreate failed: {r.status_code} {r.text[:300]}")
    return r.json()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually perform archive+recreate. Default is dry-run.")
    args = ap.parse_args()

    listings = list_swarm_listings()
    if not listings:
        print("No swarm listings found.")
        return

    print(f"=== Found {len(listings)} active swarm listing(s) ===\n")
    todo: list[dict] = []
    for l in listings:
        price = Decimal(l.get("price_amount", "0"))
        marker = " "
        action = ""
        if price <= FLOOR_PRICE:
            marker = "✓"
            action = "(already at floor — skip)"
        else:
            marker = "→"
            action = f"-> {FLOOR_PRICE} USDC"
            todo.append(l)
        print(f"  {marker} {l['id'][:8]}  {price:>8} {l.get('price_currency','USDC')}  "
              f"{l.get('title','')[:60]:60s}  {action}")

    if not todo:
        print("\nNothing to do — all swarm listings already at floor.")
        return

    if not args.apply:
        print(f"\n[dry-run] {len(todo)} listing(s) would be archived + re-created at 0.01 USDC.")
        print("Run again with --apply to actually do it.")
        return

    print(f"\n=== Applying changes to {len(todo)} listing(s) ===\n")
    new_ids: list[str] = []
    with httpx.Client(timeout=TIMEOUT) as client:
        for l in todo:
            old_id = l["id"]
            old_price = l["price_amount"]
            title = l.get("title", "")[:50]
            try:
                archive_listing(client, old_id)
                new = recreate_listing(client, l)
                new_ids.append(new["id"])
                print(f"  ✓ {old_id[:8]} ({old_price} USDC) -> {new['id'][:8]} "
                      f"(0.01 USDC)  {title}")
            except Exception as e:
                print(f"  ✗ {old_id[:8]}  {title}: {e}", file=sys.stderr)

    print(f"\nDone. {len(new_ids)} listing(s) re-published at 0.01 USDC.")


if __name__ == "__main__":
    main()
