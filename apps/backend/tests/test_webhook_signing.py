"""Signing + verification roundtrip (ADR 008)."""

from __future__ import annotations

import time

import pytest

from agora_api.webhooks.signing import (
    SignatureInvalid,
    get_signer,
    sign_body,
    verify_signature,
)


def _b() -> bytes:
    return b'{"job_id":"abc","price":"5"}'


def test_sign_verify_roundtrip() -> None:
    get_signer.cache_clear()
    headers = sign_body(_b())
    pub = get_signer().public_key_b64
    # Should not raise
    verify_signature(pub, headers["X-Agora-Signature"], headers["X-Agora-Timestamp"], _b())


def test_rejects_tampered_body() -> None:
    get_signer.cache_clear()
    headers = sign_body(_b())
    pub = get_signer().public_key_b64
    with pytest.raises(SignatureInvalid):
        verify_signature(
            pub, headers["X-Agora-Signature"], headers["X-Agora-Timestamp"], b'{"tampered":true}'
        )


def test_rejects_stale_timestamp() -> None:
    get_signer.cache_clear()
    pub = get_signer().public_key_b64
    headers = sign_body(_b())
    # Use a long-ago timestamp; the signature won't match anyway but the
    # age-check should trip first if we hand-craft a verifying sig... we
    # just check the age path directly.
    old_ts = int(time.time()) - 10_000
    with pytest.raises(SignatureInvalid, match="too old"):
        verify_signature(pub, headers["X-Agora-Signature"], old_ts, _b())


def test_rejects_garbage_signature() -> None:
    get_signer.cache_clear()
    pub = get_signer().public_key_b64
    with pytest.raises(SignatureInvalid):
        verify_signature(pub, "not-base64-!!!", str(int(time.time())), _b())


def test_rejects_garbage_pubkey() -> None:
    get_signer.cache_clear()
    headers = sign_body(_b())
    with pytest.raises(SignatureInvalid):
        verify_signature("not-base64-pubkey", headers["X-Agora-Signature"], headers["X-Agora-Timestamp"], _b())


def test_sdk_verifier_matches_backend() -> None:
    """The SDK's verify_request must accept a backend-signed body."""
    from agora_sdk.webhooks import verify_request as sdk_verify

    get_signer.cache_clear()
    headers = sign_body(_b())
    pub = get_signer().public_key_b64
    # Should not raise
    sdk_verify(pub, headers["X-Agora-Signature"], headers["X-Agora-Timestamp"], _b())
