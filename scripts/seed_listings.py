"""Seed marketplace listings (Sprint 10).

Run against a live API to populate it with sample listings so the
marketplace UI has something to render. Idempotent-ish: each run
creates fresh listings (no dedupe yet — re-run = more copies).

Usage:
    AGORA_BASE_URL=https://api.agoraproto.org python scripts/seed_listings.py

For local dev:
    AGORA_BASE_URL=http://127.0.0.1:8000 python scripts/seed_listings.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request


BASE = os.environ.get("AGORA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

# Real on-chain wallets we've used so far on Sepolia (see Sprint-9 milestone
# docs). All listings get this payout wallet so we can actually settle them
# during marketplace dogfooding. For real production use the seller would
# bring their own.
DEMO_PAYOUT_WALLET = "0xf216889923a4fC804468CFA74cC49A49E49e27E7"

# Some agent DIDs we already have on the live server (Sprint 5 + 8).
ECHO_AGENT_DID = "did:agora:9mwxtKaL9YekaULMWJNYjg"
ALICE_DID = "did:agora:4mrYSXT_f69BiaSeo7vmaA"

# Synthetic user DID for the human-seller listings. When Sprint 10d adds
# Privy auth this should be replaced with a real user DID created
# through that flow.
DEMO_HUMAN_DID = "did:agora:demo_human_seller_v1"


LISTINGS: list[dict] = [
    # ── Digital products ──────────────────────────────────────
    {
        "seller_kind": "user",
        "seller_did": DEMO_HUMAN_DID,
        "payout_wallet": DEMO_PAYOUT_WALLET,
        "listing_type": "digital_product",
        "title": "Cold-email opener pack (50 prompts)",
        "description": (
            "Fifty cold-email opening lines that have measurably outperformed "
            "the SaaS baseline in A/B tests across 12 industries (sample size "
            "≈ 2.4M sends, June 2025 – Feb 2026). Markdown bundle with usage "
            "notes for each line — when to use it, when to avoid it. Designed "
            "to be dropped into a sales-engagement LLM as a few-shot context."
        ),
        "category": "prompts",
        "tags": ["sales", "email", "outreach", "templates"],
        "price_amount": "1.50",
        "price_currency": "USDC",
        "digital_content_type": "text/markdown",
        "digital_content": {
            "filename": "cold-email-openers.md",
            "text": (
                "# 50 Cold-Email Openers\n\n"
                "## Industry: SaaS\n"
                "1. \"Saw you just shipped {feature} — quick question about the rollout.\"\n"
                "2. \"Wrong person? I was looking for whoever owns {topic} at {company}.\"\n"
                "...\n"
                "(redacted in the demo seed — full pack is delivered on purchase.)\n"
            ),
        },
        "cover_image_url": None,
    },
    {
        "seller_kind": "user",
        "seller_did": DEMO_HUMAN_DID,
        "payout_wallet": DEMO_PAYOUT_WALLET,
        "listing_type": "digital_product",
        "title": "German legal-NER training set (5k labeled sentences)",
        "description": (
            "Five thousand German sentences from public legal documents "
            "(BGH decisions, public commercial register filings, "
            "Bundesanzeiger), annotated with five entity types: PERSON, "
            "ORG, COURT, LAW_REF, MONEY. CC-BY-4.0 licensed. Designed for "
            "fine-tuning small models on legal text understanding. JSONL "
            "format, one example per line."
        ),
        "category": "datasets",
        "tags": ["nlp", "german", "legal", "ner", "training-data"],
        "price_amount": "12.00",
        "price_currency": "USDC",
        "digital_content_type": "application/json",
        "digital_content": {
            "filename": "de_legal_ner_5k.jsonl",
            "preview": [
                {"text": "Der BGH entschied am 14. März 2024…", "entities": "[redacted]"},
                {"text": "Müller GmbH zahlt 250.000 € Vertragsstrafe…", "entities": "[redacted]"},
            ],
            "note": "Full 5000 examples delivered on purchase via download URL.",
        },
        "cover_image_url": None,
    },
    {
        "seller_kind": "user",
        "seller_did": DEMO_HUMAN_DID,
        "payout_wallet": DEMO_PAYOUT_WALLET,
        "listing_type": "digital_product",
        "title": "Custom GPT system prompt: senior product designer",
        "description": (
            "Drop-in system prompt for ChatGPT, Claude, or any LLM. Turns "
            "the model into a senior product designer who pushes back on "
            "underspecified requests, surfaces edge cases, suggests "
            "research before pixels. Tested with 200+ real product briefs. "
            "Includes a short 'how to use this with your team' guide."
        ),
        "category": "custom-gpts",
        "tags": ["product-design", "ux", "system-prompt", "llm"],
        "price_amount": "0.75",
        "price_currency": "USDC",
        "digital_content_type": "text/plain",
        "digital_content": {
            "filename": "senior-product-designer.system.txt",
            "text": (
                "You are a senior product designer with 15 years at small "
                "and large companies. Your job is not to render pixels but "
                "to ask the questions that should have been asked before the "
                "brief was written...\n[redacted in seed]"
            ),
        },
        "cover_image_url": None,
    },
    # ── AI services ───────────────────────────────────────────
    {
        "seller_kind": "agent",
        "seller_did": ECHO_AGENT_DID,
        "payout_wallet": DEMO_PAYOUT_WALLET,
        "listing_type": "service",
        "title": "Echo as a service — instant smoke-test",
        "description": (
            "Send any payload, get it back. Used for testing the full x402 "
            "lifecycle without spending real compute. Useful when you're "
            "building an integration against Agora and need a guaranteed-"
            "responsive provider on the other side. Settles in seconds."
        ),
        "category": "infrastructure",
        "tags": ["smoke-test", "echo", "integration-test", "demo"],
        "price_amount": "0.50",
        "price_currency": "USDC",
        "service_capability": "Echo",
        "service_input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Anything you want echoed."},
            },
            "required": ["text"],
        },
        "cover_image_url": None,
    },
    {
        "seller_kind": "agent",
        "seller_did": ECHO_AGENT_DID,
        "payout_wallet": DEMO_PAYOUT_WALLET,
        "listing_type": "service",
        "title": "Translation EN → DE, formal register",
        "description": (
            "Single-message translation from English to German. Defaults to "
            "formal register ('Sie', not 'du'). Drops at most 3 idiomatic "
            "passes and prefers literal fidelity for technical and legal "
            "content. Returns the translation plus a brief notes section "
            "flagging any phrases that don't carry over cleanly."
        ),
        "category": "translation",
        "tags": ["english", "german", "translation", "formal"],
        "price_amount": "0.80",
        "price_currency": "USDC",
        "service_capability": "Translation",
        "service_input_schema": {
            "type": "object",
            "properties": {
                "source_lang": {"type": "string", "default": "en"},
                "target_lang": {"type": "string", "default": "de"},
                "text": {"type": "string"},
                "register": {"type": "string", "enum": ["formal", "informal"], "default": "formal"},
            },
            "required": ["text"],
        },
        "cover_image_url": None,
    },
]


def post_listing(payload: dict) -> dict:
    """POST to /v1/listings, return the created listing dict."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=f"{BASE}/v1/listings",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(
            f"\n  POST {BASE}/v1/listings failed: HTTP {e.code}\n  body: {body}\n"
            f"  payload was: {json.dumps(payload)[:200]}…"
        ) from e


def main() -> int:
    print(f"Seeding {len(LISTINGS)} listings against {BASE}")
    created = []
    for i, listing in enumerate(LISTINGS, 1):
        out = post_listing(listing)
        created.append(out)
        print(f"  [{i}/{len(LISTINGS)}] {out['id']}  {out['title']}  ({out['price_amount']} {out['price_currency']})")
    print(f"\nDone — {len(created)} listings live at {BASE}/v1/listings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
