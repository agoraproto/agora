"""Ed25519 webhook signing (ADR 008).

Why asymmetric (vs HMAC)?
- Agents store only a SHA-256 hash of their per-agent webhook_secret, so the
  backend cannot sign outbound HMACs without holding plaintext (which would
  require encrypted-at-rest storage). One Agora-owned Ed25519 keypair is
  simpler operationally, rotatable, and verifiable by anyone who fetches
  /.well-known/agora.json.

Signed payload (canonical):
    f"{timestamp}.".encode() + body   # body is the raw HTTP body bytes
    timestamp = unix seconds (UTC)
"""

from __future__ import annotations

import base64
import sys
import time
from dataclasses import dataclass
from functools import lru_cache

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from ..config import get_settings


class SignatureInvalid(Exception):
    """Raised when a webhook signature fails verification (bad sig or stale)."""


@dataclass(frozen=True)
class AgoraSigner:
    """Holds Agora's Ed25519 signing key and key-id."""

    signing_key: SigningKey
    key_id: str

    @property
    def verify_key(self) -> VerifyKey:
        return self.signing_key.verify_key

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self.verify_key.encode()).decode("ascii")

    def sign(self, body: bytes, timestamp: int | None = None) -> tuple[str, int]:
        """Sign `body` with current timestamp; return (signature_b64, timestamp)."""
        ts = int(time.time()) if timestamp is None else timestamp
        payload = f"{ts}.".encode() + body
        sig = self.signing_key.sign(payload).signature
        return base64.b64encode(sig).decode("ascii"), ts


def _load_or_generate_signer() -> AgoraSigner:
    """Load signer from settings; generate ephemeral one for local dev if unset."""
    settings = get_settings()
    privkey_b64 = getattr(settings, "agora_signing_private_key_b64", "")
    key_id = getattr(settings, "agora_signing_key_id", "agora-local-dev")

    if privkey_b64:
        try:
            sk = SigningKey(base64.b64decode(privkey_b64))
            return AgoraSigner(signing_key=sk, key_id=key_id)
        except Exception as e:
            raise RuntimeError(f"invalid AGORA_SIGNING_PRIVATE_KEY_B64: {e}") from e

    # M-06 audit fix: refuse to start staging/production without a persistent
    # signing key. The previous behaviour silently generated an ephemeral key
    # on every restart, which would invalidate every outstanding webhook
    # signature on the next process restart. That's fine for local dev, but
    # for any real deployment we want the process to crash early and loudly.
    if settings.app_env != "local":
        raise RuntimeError(
            f"AGORA_SIGNING_PRIVATE_KEY_B64 must be set in env={settings.app_env}. "
            "Generate one with:  python -c 'import base64, nacl.signing; "
            "print(base64.b64encode(nacl.signing.SigningKey.generate().encode()).decode())'  "
            "and set it as a 32-byte-Ed25519-private-key (base64). "
            "Refusing to start with an ephemeral key in non-local mode."
        )

    sk = SigningKey.generate()
    print(
        f"[agora.signing] dev-mode ephemeral key generated. key_id={key_id} "
        f"pubkey={base64.b64encode(sk.verify_key.encode()).decode('ascii')}",
        file=sys.stderr,
        flush=True,
    )
    return AgoraSigner(signing_key=sk, key_id=key_id)


@lru_cache(maxsize=1)
def get_signer() -> AgoraSigner:
    """Module-singleton signer. Reload by clearing this cache after rotation."""
    return _load_or_generate_signer()


def public_key_b64() -> str:
    return get_signer().public_key_b64


def sign_body(body: bytes) -> dict[str, str]:
    """Return the headers a delivery should ship with."""
    signer = get_signer()
    sig, ts = signer.sign(body)
    return {
        "X-Agora-Signature": sig,
        "X-Agora-Timestamp": str(ts),
        "X-Agora-Key-Id": signer.key_id,
    }


def verify_signature(
    public_key_b64_str: str,
    signature_b64: str,
    timestamp: int | str,
    body: bytes,
    *,
    max_age_seconds: int = 300,
) -> None:
    """Verify an Agora webhook. Raises `SignatureInvalid` on any failure."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError) as e:
        raise SignatureInvalid(f"invalid timestamp: {timestamp!r}") from e

    # Sprint 39 / B-V2-02 fix: one-sided window. Reject anything older
    # than max_age_seconds OR meaningfully in the future. The previous
    # abs() check allowed up to 5 min future timestamps, which is unusual
    # for webhook verification (signatures should be observably in the
    # past at delivery time).
    now = int(time.time())
    age = now - ts
    if age > max_age_seconds:
        raise SignatureInvalid(
            f"timestamp {ts} too old (age={age}s, max={max_age_seconds}s)"
        )
    if age < -30:
        # Allow up to 30s of clock-skew for legitimate sources; reject
        # anything claiming to be from a meaningful future.
        raise SignatureInvalid(
            f"timestamp {ts} is too far in the future (skew={-age}s)"
        )

    try:
        vk = VerifyKey(base64.b64decode(public_key_b64_str))
        sig = base64.b64decode(signature_b64)
    except Exception as e:
        raise SignatureInvalid(f"malformed signature or pubkey: {e}") from e

    payload = f"{ts}.".encode() + body
    try:
        vk.verify(payload, sig)
    except BadSignatureError as e:
        raise SignatureInvalid("signature does not verify") from e
