"""Sprint 20 — Audit Document Gap Checker provider loop.

Polls /v1/jobs for jobs offered to this agent's DID, runs the task
through Claude Haiku with the compliance-auditor system prompt, parses
the JSON output, and submits the result on-chain via the SDK's x402
helper (submitResult → backend mirror).

Run with:
  ANTHROPIC_API_KEY=sk-... python3 agent.py

The credentials.json lives next to this file (see register.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx

API = os.environ.get("AGORA_API", "https://api.agoraproto.org")
RPC = os.environ.get("AGORA_RPC", "https://sepolia.base.org")
POLL_INTERVAL = int(os.environ.get("AUDIT_POLL_INTERVAL", "20"))
MODEL = os.environ.get("AGORA_AUDIT_MODEL", "claude-haiku-4-5-20251001")
MAX_TOKENS = int(os.environ.get("AGORA_AUDIT_MAX_TOKENS", "4000"))

HERE = Path(__file__).parent
CREDS_FILE = HERE / "data" / "credentials.json"
PROMPT_FILE = HERE / "system_prompt.md"

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [audit] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("audit_agent")


# ─────────────────────────────────────────────────────────────────────
# LLM call (own copy — swarm.lib.llm caps at 512 tokens, too small)
# ─────────────────────────────────────────────────────────────────────


async def call_claude(system_prompt: str, task_spec: dict[str, Any]) -> str:
    """One call to Claude Haiku. Returns raw text (expected to be JSON)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY missing — returning stub JSON")
        return json.dumps({
            "markdown_report": "# Compliance Gap Report\n\n_Stub — ANTHROPIC_API_KEY not configured._",
            "summary": {
                "standard": str(task_spec.get("standard", "iso9001")),
                "document_excerpt": str(task_spec.get("document", ""))[:120],
                "satisfied_clauses": [],
                "gap_clauses": [],
                "unclear_clauses": [],
                "overall_score_pct": 0,
                "critical_gaps_count": 0,
                "top_recommendations": ["Set ANTHROPIC_API_KEY on the agent host."],
            },
        })

    user_msg = json.dumps(task_spec, ensure_ascii=False)
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
    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.post(ANTHROPIC_URL, json=payload, headers=headers)
    if r.status_code != 200:
        log.error("LLM call failed: %s %s", r.status_code, r.text[:300])
        return json.dumps({
            "markdown_report": f"# Error\n\nLLM call failed: HTTP {r.status_code}",
            "summary": {
                "standard": str(task_spec.get("standard", "iso9001")),
                "document_excerpt": str(task_spec.get("document", ""))[:120],
                "satisfied_clauses": [], "gap_clauses": [], "unclear_clauses": [],
                "overall_score_pct": 0, "critical_gaps_count": 0,
                "top_recommendations": [],
            },
        })
    data = r.json()
    parts = data.get("content", [])
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    return text.strip()


def parse_json_envelope(raw: str) -> dict[str, Any]:
    """Best-effort extraction of the JSON object from Claude's output.

    The system prompt asks for a bare JSON object, but Haiku sometimes
    wraps it in ```json ... ``` or prepends a sentence. We strip the
    common envelopes and fall back to a "first '{' to last '}'" slice.
    """
    txt = raw.strip()
    # Strip ```json fences if present.
    if txt.startswith("```"):
        # remove the opening fence
        first_nl = txt.find("\n")
        if first_nl != -1:
            txt = txt[first_nl + 1:]
        # remove trailing ```
        if txt.rstrip().endswith("```"):
            txt = txt.rstrip()[:-3].rstrip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        # Fall back: slice first { to last }
        i, j = txt.find("{"), txt.rfind("}")
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(txt[i:j + 1])
            except json.JSONDecodeError:
                pass
    # Give the buyer SOMETHING useful even if the LLM mis-formatted.
    return {
        "markdown_report": "# Compliance Gap Report\n\n_LLM output was not valid JSON — raw text below._\n\n" + raw[:4000],
        "summary": {
            "standard": "unknown",
            "document_excerpt": "",
            "satisfied_clauses": [],
            "gap_clauses": [],
            "unclear_clauses": [],
            "overall_score_pct": 0,
            "critical_gaps_count": 0,
            "top_recommendations": [],
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Provider loop
# ─────────────────────────────────────────────────────────────────────


class AuditAgent:
    def __init__(self, did: str, address: str, private_key: str, system_prompt: str) -> None:
        self.did = did
        self.address = address
        self.private_key = private_key
        self.system_prompt = system_prompt
        self.handled: set[str] = set()

    async def run(self) -> None:
        log.info("audit agent online (did=%s, addr=%s, poll=%ds)",
                 self.did, self.address, POLL_INTERVAL)
        while True:
            try:
                await self._tick()
            except Exception as e:
                log.exception("tick failed: %s", e)
            await asyncio.sleep(POLL_INTERVAL)

    async def _tick(self) -> None:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.get(
                f"{API}/v1/jobs",
                params={"provider_did": self.did, "status": "offered"},
            )
        if r.status_code != 200:
            return
        data = r.json()
        jobs = data.get("jobs") if isinstance(data, dict) else data
        if not jobs:
            return
        async with httpx.AsyncClient(timeout=20) as http:
            for job in jobs:
                jid = job.get("id")
                if not jid or jid in self.handled:
                    continue
                rd = await http.get(f"{API}/v1/jobs/{jid}")
                if rd.status_code != 200:
                    continue
                full = rd.json()
                if full.get("status") != "offered":
                    self.handled.add(jid)
                    continue
                await self._handle_job(full)
                self.handled.add(jid)

    async def _handle_job(self, job: dict) -> None:
        jid = job["id"]
        task_spec = job.get("task_spec", {}) or {}
        log.info("handling job %s (standard=%s, doc_len=%d)",
                 jid, task_spec.get("standard"),
                 len(str(task_spec.get("document", ""))))

        raw = await call_claude(self.system_prompt, task_spec)
        envelope = parse_json_envelope(raw)
        # The deliverable is the structured envelope; we also stash the
        # raw text in case the buyer wants to inspect it.
        result_payload = {
            **envelope,
            "by": self.did,
            "capability": "AuditDocumentGapCheck",
        }

        try:
            from agora_sdk.x402 import submit_result_with_x402
        except ImportError:
            log.error("agora_sdk not installed; "
                      "install with: pip install -e /opt/agora/packages/sdk-python")
            return

        try:
            res = await submit_result_with_x402(
                API,
                job_id=jid,
                result=result_payload,
                rpc_url=RPC,
                private_key=self.private_key,
            )
            score = result_payload.get("summary", {}).get("overall_score_pct", "?")
            gaps = result_payload.get("summary", {}).get("critical_gaps_count", "?")
            log.info("job %s submitted: status=%s score=%s%% critical_gaps=%s",
                     jid, res.get("status"), score, gaps)
        except Exception as e:
            log.exception("submit_result failed for %s: %s", jid, e)


# ─────────────────────────────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────────────────────────────


def load_credentials() -> dict:
    if not CREDS_FILE.is_file():
        sys.exit(f"missing {CREDS_FILE} — run register.py first")
    return json.loads(CREDS_FILE.read_text())


def load_system_prompt() -> str:
    if not PROMPT_FILE.is_file():
        sys.exit(f"missing {PROMPT_FILE}")
    return PROMPT_FILE.read_text()


async def main() -> None:
    creds = load_credentials()
    prompt = load_system_prompt()
    agent = AuditAgent(
        did=creds["did"],
        address=creds["evm_address"],
        private_key=creds["evm_private_key_hex"],
        system_prompt=prompt,
    )
    await agent.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("interrupted — bye")
