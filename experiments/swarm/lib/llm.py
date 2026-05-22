"""Anthropic Claude Haiku wrapper for swarm agents.

Each provider has a `system_prompt` (from personalities.py). When a
task arrives, we call Anthropic with the system prompt + the buyer's
task_spec as the user message. Tokens are cheap (Haiku), so we just
log usage and move on. Failures fall back to a deterministic stub so
the demo never gets stuck.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("AGORA_SWARM_MODEL", "claude-haiku-4-5-20251001")
MAX_TOKENS = 512


async def ask(system_prompt: str, task_spec: dict[str, Any]) -> str:
    """Run one LLM call. Returns plain text (the agent's deliverable)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY missing — returning stub")
        return f"[stub-result for task {json.dumps(task_spec)[:80]}]"

    user_msg = json.dumps(task_spec, indent=2)
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_msg}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(ANTHROPIC_URL, json=payload, headers=headers)
    if r.status_code != 200:
        log.error("LLM call failed: %s %s", r.status_code, r.text[:200])
        return f"[error: HTTP {r.status_code}]"

    data = r.json()
    parts = data.get("content", [])
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    return text.strip() or "[empty response]"
