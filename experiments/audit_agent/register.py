"""Sprint 20 — Audit Document Gap Checker, registration / one-shot bootstrap.

Uses the Sprint-19 POST /v1/agents/bootstrap convenience endpoint so we
don't have to assemble Ed25519 keys + DID-document + EVM wallet + fund-
tx by hand. The server generates everything and ships it back exactly
once; we persist it to data/credentials.json (mode 600) and then create
the service listing.

Idempotent: if credentials.json already exists we skip bootstrap and only
ensure the listing is present.

Usage:
  python3 register.py            # bootstrap + listing (default)
  python3 register.py --listing  # only (re)create the listing
  python3 register.py --print    # show DID + wallet (no secrets)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

API = os.environ.get("AGORA_API", "https://api.agoraproto.org")
HERE = Path(__file__).parent
DATA = HERE / "data"
CREDS = DATA / "credentials.json"
LISTING = DATA / "listing.json"

AGENT_NAME = "Audit Document Gap Checker"
AGENT_DESC = (
    "Automated compliance gap analysis for ISO 9001, IATF 16949, CSR (customer-"
    "specific OEM requirements) and ISO 14001. Paste any policy excerpt, "
    "process description or manual page; receive a structured Markdown report "
    "plus a JSON summary highlighting satisfied clauses, gaps with severity, "
    "and the top 3-5 actions to close them. Built for KMU suppliers in the "
    "automotive value chain who need a quick second-opinion before their next "
    "internal or 3rd-party audit."
)
CAPABILITY = "AuditDocumentGapCheck"
PRICE_USDC = "2.50"

LISTING_TITLE = "Audit Document Gap Check — ISO 9001 / IATF 16949 / CSR / ISO 14001"
LISTING_DESCRIPTION = (
    "Compliance auditor for QM/EMS/automotive standards. Send a document "
    "excerpt with the target standard; receive a clause-by-clause gap report "
    "in under a minute.\n\n"
    "**Supported standards**\n"
    "- ISO 9001:2015 — Quality Management Systems\n"
    "- IATF 16949:2016 — Automotive QMS (PPAP, APQP, FMEA, MSA, SPC, layered audits)\n"
    "- CSR — Customer-specific requirements (Ford SQ/Q1, Stellantis SSC, JLR SQR, VW Formel-Q, Daimler MBST)\n"
    "- ISO 14001:2015 — Environmental Management Systems\n\n"
    "**Input**\n"
    "`{ document: str, standard: 'iso9001' | 'iatf16949' | 'csr' | 'iso14001' | 'all' }`\n\n"
    "**Output**\n"
    "JSON with `markdown_report` (string) and `summary` "
    "(satisfied_clauses, gap_clauses with severity, unclear_clauses, "
    "overall_score_pct, top_recommendations).\n\n"
    "**Limits**\n"
    "Best for excerpts up to ~20k characters. For full manuals, split into "
    "sections. This is an automated screening — always cross-check critical "
    "findings against the actual standard before making compliance decisions."
)
INPUT_SCHEMA_HINT = (
    "{ document: str, standard: 'iso9001' | 'iatf16949' | 'csr' | 'iso14001' | 'all' }"
)
CATEGORY = "compliance"
TAGS = ["audit", "compliance", "iso9001", "iatf16949", "csr", "iso14001", "qm", "automotive"]


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _ensure_data_dir() -> None:
    DATA.mkdir(parents=True, exist_ok=True)


def _save_creds(creds: dict) -> None:
    _ensure_data_dir()
    CREDS.write_text(json.dumps(creds, indent=2))
    try:
        os.chmod(CREDS, 0o600)
    except Exception as e:
        print(f"  ! could not chmod 600 {CREDS}: {e}", file=sys.stderr)


def _load_creds() -> dict | None:
    if not CREDS.is_file():
        return None
    try:
        return json.loads(CREDS.read_text())
    except Exception as e:
        sys.exit(f"credentials.json unreadable: {e}")


# ─────────────────────────────────────────────────────────────────────
# Bootstrap
# ─────────────────────────────────────────────────────────────────────


def bootstrap_agent() -> dict:
    """Call POST /v1/agents/bootstrap and persist the credentials."""
    body = {
        "name": AGENT_NAME,
        "description": AGENT_DESC,
        "capabilities": [CAPABILITY],
        "pricing": {
            "model": "per_request",
            "currency": "USDC",
            "base_price": PRICE_USDC,
        },
        "endpoint_url": "",  # poll-based, no webhook
        "fund_eth": True,    # server tops up wallet for gas
    }
    print(f"→ POST {API}/v1/agents/bootstrap")
    r = httpx.post(f"{API}/v1/agents/bootstrap", json=body, timeout=60)
    if r.status_code != 201:
        sys.exit(f"bootstrap failed {r.status_code}: {r.text[:500]}")
    creds = r.json()
    _save_creds(creds)
    print(f"  ✓ did            = {creds['did']}")
    print(f"  ✓ evm_address    = {creds['evm_address']}")
    print(f"  ✓ funded         = {creds.get('funded_eth_amount', '?')} ETH "
          f"(tx={creds.get('funded_eth_tx')}, err={creds.get('funded_eth_error')})")
    print(f"  ✓ credentials    → {CREDS} (mode 600)")
    return creds


# ─────────────────────────────────────────────────────────────────────
# Listing
# ─────────────────────────────────────────────────────────────────────


def create_listing(creds: dict) -> dict:
    """Publish the marketplace listing for the audit service."""
    body = {
        "seller_kind": "agent",
        "seller_did": creds["did"],
        "payout_wallet": creds["evm_address"],
        "listing_type": "service",
        "title": LISTING_TITLE,
        "description": LISTING_DESCRIPTION,
        "category": CATEGORY,
        "tags": TAGS,
        "price_amount": PRICE_USDC,
        "price_currency": "USDC",
        "service_capability": CAPABILITY,
        "service_input_schema": {"schema_hint": INPUT_SCHEMA_HINT},
    }
    print(f"→ POST {API}/v1/listings")
    r = httpx.post(f"{API}/v1/listings", json=body, timeout=30)
    if r.status_code != 201:
        sys.exit(f"listing failed {r.status_code}: {r.text[:500]}")
    listing = r.json()
    _ensure_data_dir()
    LISTING.write_text(json.dumps(listing, indent=2))
    print(f"  ✓ listing.id     = {listing['id']}")
    print(f"  ✓ price          = {listing['price_amount']} {listing['price_currency']}")
    print(f"  ✓ listing        → {LISTING}")
    return listing


# ─────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listing", action="store_true",
                    help="Only (re)create the listing; reuse existing credentials.")
    ap.add_argument("--print", dest="show", action="store_true",
                    help="Show DID + wallet from existing credentials.json (no secrets).")
    args = ap.parse_args()

    if args.show:
        creds = _load_creds()
        if not creds:
            sys.exit("no credentials.json — run register.py first")
        print(f"did         = {creds['did']}")
        print(f"name        = {creds.get('name')}")
        print(f"trust_level = {creds.get('trust_level')}")
        print(f"evm_address = {creds['evm_address']}")
        print(f"funded      = {creds.get('funded_eth_amount')} ETH "
              f"tx={creds.get('funded_eth_tx')}")
        return

    if args.listing:
        creds = _load_creds()
        if not creds:
            sys.exit("no credentials.json — run without --listing first")
        create_listing(creds)
        return

    creds = _load_creds()
    if creds:
        print(f"• credentials.json already present → reusing {creds['did']}")
    else:
        creds = bootstrap_agent()

    if LISTING.is_file():
        existing = json.loads(LISTING.read_text())
        print(f"• listing.json already present → {existing.get('id')} "
              f"({existing.get('price_amount')} USDC)")
    else:
        create_listing(creds)

    print("\nDone. Start the agent with:")
    print("  python3 agent.py")


if __name__ == "__main__":
    main()
