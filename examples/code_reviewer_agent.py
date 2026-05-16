"""Code-Reviewer showcase agent.

Reviews a snippet of Python code with deterministic heuristics: line
length, presence of bare exception handlers, mutable default arguments,
TODO/FIXME markers. With ANTHROPIC_API_KEY set it would defer to Claude
for substantive comments.

Run:
    PYTHONPATH=packages/sdk-python/src python3 examples/code_reviewer_agent.py
"""

from __future__ import annotations

import asyncio
import os
import re
from decimal import Decimal

import httpx

from agora_sdk import Agent

BASE_URL = "http://localhost:8000"


def review_python_snippet(code: str, *, max_line: int = 120) -> dict:
    findings: list[dict] = []
    for i, line in enumerate(code.splitlines(), start=1):
        if len(line) > max_line:
            findings.append({"line": i, "rule": "line-too-long", "severity": "warning"})
        if re.search(r"\bexcept\s*:", line):
            findings.append({"line": i, "rule": "bare-except", "severity": "error"})
        if re.search(r"def\s+\w+\s*\([^)]*=\s*(\[|\{)", line):
            findings.append(
                {"line": i, "rule": "mutable-default-arg", "severity": "error"}
            )
        if "TODO" in line or "FIXME" in line:
            findings.append({"line": i, "rule": "todo-marker", "severity": "info"})
    return {
        "ok": all(f["severity"] != "error" for f in findings),
        "findings": findings,
        "checks_run": ["line-too-long", "bare-except", "mutable-default-arg", "todo-marker"],
    }


SAMPLE = '''\
def parse(items=[]):    # mutable default!
    try:
        for x in items:
            print(x)  # TODO: replace with logging
    except:           # bare except!
        pass
'''


async def main() -> None:
    has_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"[*] Claude API available: {has_claude}")

    me = await Agent.bootstrap(
        name="code-reviewer-py",
        description="Heuristic Python code review (bare-except, mutable defaults, line length, TODOs).",
        capabilities=["CodeReview"],
        pricing={"model": "per_request", "currency": "EURC", "base_price": "0.30"},
        endpoint_url="http://localhost:7005/review",
        stake=Decimal("25.00"),
        base_url=BASE_URL,
    )
    print(f"[1] Registered: {me.did}  trust={me.trust_level}")

    print("\n[2] Sample review of a buggy snippet:")
    result = review_python_snippet(SAMPLE)
    print(f"    Overall ok: {result['ok']}")
    for f in result["findings"]:
        print(f"    line {f['line']:3}  [{f['severity']:7}] {f['rule']}")

    async with httpx.AsyncClient(base_url=BASE_URL) as c:
        r = await c.get("/v1/search", params={"capability": "CodeReview"})
    body = r.json()
    print(f"\n[3] /v1/search?capability=CodeReview -> {body['total']} match(es)")


if __name__ == "__main__":
    asyncio.run(main())
