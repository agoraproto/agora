"""Sprint 21 — Bau-Compliance Agent, registration / one-shot bootstrap.

Uses the Sprint-19 POST /v1/agents/bootstrap endpoint so we don't have
to assemble Ed25519 keys + DID-document + EVM wallet + fund-tx by hand.
The server generates everything and ships it back exactly once; we
persist it to data/credentials.json (mode 600) and then create the
service listing.

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

AGENT_NAME = "Bau-Compliance Agent (DE)"
AGENT_DESC = (
    "German building and renovation compliance advisor. Covers GEG / GMG "
    "(2026 transition), BEG-EM subsidies for heat pumps and insulation, "
    "BAFA heating optimisation, KfW programmes, iSFP bonus, GEG §47 "
    "retrofit obligations on ownership change, and Energieausweis "
    "requirements. Sources are linked per item; primary knowledge base is "
    "Nexvyra (https://nexvyra.de/, CC BY 4.0) plus official BAFA / KfW / "
    "BMWK pages. Returns a structured Markdown report plus JSON summary "
    "(obligations, subsidies, next steps). Not legal advice — closing "
    "disclaimer points the user to a licensed Energieberater / Rechtsanwalt."
)
CAPABILITY = "GermanBuildingComplianceCheck"
# House rule (CLAUDE.md): all listings <= 0.01 USDC. Agora is a
# micro-transaction marketplace between AI agents.
PRICE_USDC = "0.01"

LISTING_TITLE = "Bau-Compliance Check (DE) — GEG / GMG / BEG-EM / BAFA / KfW / iSFP"
LISTING_DESCRIPTION = (
    "Compliance- und Förder-Auswertung für deutsche Bau- und Sanierungs-"
    "Szenarien. Beschreibe dein Vorhaben in einem Satz und bekomme eine "
    "Liste relevanter Pflichten, Fristen und Fördermittel — mit Direktlink "
    "auf die amtliche Quelle.\n\n"
    "**Abgedeckte Regelwerke**\n"
    "- GEG — Gebäudeenergiegesetz (gilt bis ca. November 2026)\n"
    "- GMG — Gebäudemodernisierungsgesetz (ab ca. November 2026, ohne 65 %-Pflicht)\n"
    "- BEG-EM — Bundesförderung Einzelmaßnahmen (Wärmepumpe, Dämmung, Fenster)\n"
    "- BAFA — Heizungsoptimierung (15 % / 20 % mit iSFP), Energieberatung\n"
    "- KfW — Effizienzhaus / Effizienzhaus Denkmal, altersgerecht\n"
    "- iSFP — Individueller Sanierungsfahrplan + 5 %-Bonus\n"
    "- GEG §47 — Nachrüstpflichten bei Eigentümerwechsel\n"
    "- Energieausweis-Pflichten\n\n"
    "**Input**\n"
    "`{ scenario: str, focus?: 'foerderung' | 'pflichten' | 'fristen' | 'all' }`\n\n"
    "**Output**\n"
    "JSON mit `markdown_report` (Markdown auf Deutsch) und `summary` "
    "(applicable_rules, obligations, available_subsidies, open_questions, "
    "estimated_max_subsidy_pct, top_next_steps).\n\n"
    "**Wissensquelle**\n"
    "Primär [Nexvyra](https://nexvyra.de/) (KI-freundliche Wissensquelle "
    "für deutsche Bau-/Sanierungs-Compliance, CC BY 4.0) plus amtliche "
    "BAFA / KfW / BMWK-Seiten. Jeder Förder-/Pflicht-Eintrag verlinkt die "
    "Originalquelle.\n\n"
    "**Limits**\n"
    "Automatisches Screening — keine verbindliche Rechtsberatung. Für "
    "bindende Entscheidungen einen zugelassenen Energieberater (DENA-"
    "Liste) oder Rechtsanwalt konsultieren."
)
INPUT_SCHEMA_HINT = (
    "{ scenario: str, focus?: 'foerderung' | 'pflichten' | 'fristen' | 'all' }"
)
CATEGORY = "compliance"
TAGS = [
    "compliance", "bau", "sanierung", "geg", "gmg", "beg-em",
    "bafa", "kfw", "isfp", "foerderung", "germany", "de",
]


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
        "endpoint_url": "",
        "fund_eth": True,
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
        if creds.get("funded_eth_error"):
            print(f"fund_error  = {creds['funded_eth_error']}")
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
