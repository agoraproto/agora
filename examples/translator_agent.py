"""Translator showcase agent (DE <-> EN, sehr klein).

Self-registers as 'translator-de-en' and offers a deterministic
phrase-book translation for a small set of inputs. With ANTHROPIC_API_KEY
set it would fall back to Claude for everything else.

Run:
    PYTHONPATH=packages/sdk-python/src python3 examples/translator_agent.py
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import httpx

from agora_sdk import Agent

BASE_URL = "http://localhost:8000"

PHRASE_BOOK_DE_EN: dict[str, str] = {
    "hallo welt": "Hello, World",
    "guten morgen": "Good morning",
    "wie geht es dir": "How are you",
    "danke schön": "Thank you very much",
    "ich liebe dich": "I love you",
}


def translate_local(text: str, source: str, target: str) -> dict:
    if source == "de" and target == "en":
        key = text.lower().strip().rstrip("?!.")
        if key in PHRASE_BOOK_DE_EN:
            return {"translation": PHRASE_BOOK_DE_EN[key], "source": "phrase-book"}
    return {
        "translation": None,
        "source": "phrase-book",
        "note": "out of phrase-book; Claude fallback would handle this",
    }


async def main() -> None:
    has_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"[*] Claude API available: {has_claude}")

    me = await Agent.bootstrap(
        name="translator-de-en",
        description="Short-phrase DE/EN translation with a curated phrase book.",
        capabilities=["LegalTranslation", "LiteraryTranslation"],
        pricing={"model": "per_request", "currency": "EURC", "base_price": "0.20"},
        endpoint_url="http://localhost:7004/translate",
        stake=Decimal("25.00"),
        base_url=BASE_URL,
    )
    print(f"[1] Registered: {me.did}  trust={me.trust_level}")

    print("\n[2] Sample translations:")
    for src in ["Hallo Welt", "Guten Morgen", "Ich brauche einen Kaffee"]:
        out = translate_local(src, "de", "en")
        print(f"    DE: {src!r}")
        print(f"    EN: {out['translation']!r}  ({out['source']})")

    async with httpx.AsyncClient(base_url=BASE_URL) as c:
        r = await c.get("/v1/search", params={"capability": "LegalTranslation"})
    body = r.json()
    print(f"\n[3] /v1/search?capability=LegalTranslation -> {body['total']} match(es)")


if __name__ == "__main__":
    asyncio.run(main())
