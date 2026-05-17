"""Webhook verification for receivers (ADR 008)."""

from __future__ import annotations

import base64
import time

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey


class SignatureInvalid(Exception):
    """Raised when an incoming webhook fails signature/replay verification."""


def verify_request(
    public_key_b64: str,
    signature_b64: str,
    timestamp: int | str,
    body: bytes,
    *,
    max_age_seconds: int = 300,
) -> None:
    """Verify an Agora webhook. Raises `SignatureInvalid` on any problem."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError) as e:
        raise SignatureInvalid(f"invalid timestamp: {timestamp!r}") from e

    age = abs(int(time.time()) - ts)
    if age > max_age_seconds:
        raise SignatureInvalid(
            f"timestamp {ts} too old (age={age}s, max={max_age_seconds}s)"
        )

    try:
        vk = VerifyKey(base64.b64decode(public_key_b64))
        sig = base64.b64decode(signature_b64)
    except Exception as e:
        raise SignatureInvalid(f"malformed signature or pubkey: {e}") from e

    payload = f"{ts}.".encode() + body
    try:
        vk.verify(payload, sig)
    except BadSignatureError as e:
        raise SignatureInvalid("signature does not verify") from e


__all__ = ["SignatureInvalid", "verify_request"]
