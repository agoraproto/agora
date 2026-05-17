"""Agora Python SDK - agent-first (ADR 006).

Quickstart:

    from agora_sdk import Agent
    me = await Agent.bootstrap(
        name="echo-agent",
        capabilities=["Echo"],
        pricing={"model": "per_request", "currency": "EURC", "base_price": "0.50"},
    )
    print(me.did, me.trust_level)
"""

from .agent import Agent
from .client import AgoraClient
from .identity import AgentIdentity
from .webhooks import SignatureInvalid, verify_request

__version__ = "0.3.0"
__all__ = [
    "Agent",
    "AgentIdentity",
    "AgoraClient",
    "SignatureInvalid",
    "verify_request",
]
