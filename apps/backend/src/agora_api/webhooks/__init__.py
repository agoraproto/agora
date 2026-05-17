"""Webhook delivery subsystem (Sprint 6 / ADR 008).

Outbound webhooks from Agora to service agents are signed with Agora's
Ed25519 private key. Service agents verify with the public key published at
/.well-known/agora.json.
"""

from .signing import (
    AgoraSigner,
    SignatureInvalid,
    get_signer,
    public_key_b64,
    sign_body,
    verify_signature,
)

__all__ = [
    "AgoraSigner",
    "SignatureInvalid",
    "get_signer",
    "public_key_b64",
    "sign_body",
    "verify_signature",
]
