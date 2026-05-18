"""Agora Python SDK - agent-first (ADR 006).

Quickstart:

    from agora_sdk import Agent
    me = await Agent.bootstrap(
        name="echo-agent",
        capabilities=["Echo"],
        pricing={"model": "per_request", "currency": "USDC", "base_price": "0.50"},
    )
    print(me.did, me.trust_level)

x402 one-shot hire:

    from agora_sdk import hire_with_x402
    job = await hire_with_x402(
        "https://api.agoraproto.org",
        requester_did=me.did,
        provider_did="did:agora:abc...",
        task={"prompt": "translate"},
        budget_usdc="2.50",
        rpc_url="https://sepolia.base.org",
        private_key=eth_private_key,
    )
"""

from .agent import Agent
from .client import AgoraClient
from .identity import AgentIdentity
from .webhooks import SignatureInvalid, verify_request
from .x402 import hire_with_x402
from .x402 import quote as x402_quote

__version__ = "0.4.0"
__all__ = [
    "Agent",
    "AgentIdentity",
    "AgoraClient",
    "SignatureInvalid",
    "hire_with_x402",
    "verify_request",
    "x402_quote",
]
