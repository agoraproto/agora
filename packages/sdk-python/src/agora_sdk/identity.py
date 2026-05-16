"""DID + key management for agents (ADR 006)."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from nacl.signing import SigningKey, VerifyKey


def _b58encode(data: bytes) -> str:
    # Minimal base58 alphabet
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(data, "big")
    out = ""
    while n > 0:
        n, r = divmod(n, 58)
        out = alphabet[r] + out
    # Leading zero bytes → '1'
    for b in data:
        if b == 0:
            out = "1" + out
        else:
            break
    return out or "1"


@dataclass(frozen=True)
class AgentIdentity:
    """Ed25519 signing keypair + derived DID."""

    did: str
    signing_key: SigningKey
    verify_key: VerifyKey

    @property
    def public_key_multibase(self) -> str:
        # 0xed = ed25519 multicodec
        prefix = b"\xed\x01"
        return "z" + _b58encode(prefix + self.verify_key.encode())

    def sign(self, message: bytes) -> bytes:
        return self.signing_key.sign(message).signature

    def export_secret(self) -> str:
        """Base64-encoded private key – only for local storage / wallet export."""
        return base64.b64encode(self.signing_key.encode()).decode("ascii")

    @classmethod
    def generate(cls) -> AgentIdentity:
        sk = SigningKey.generate()
        vk = sk.verify_key
        # DID = did:agora:<short-hash-of-public-key>
        h = hashlib.sha256(vk.encode()).digest()[:16]
        did_suffix = base64.urlsafe_b64encode(h).decode("ascii").rstrip("=")
        did = f"did:agora:{did_suffix}"
        return cls(did=did, signing_key=sk, verify_key=vk)

    @classmethod
    def from_secret(cls, b64_secret: str) -> AgentIdentity:
        sk = SigningKey(base64.b64decode(b64_secret))
        vk = sk.verify_key
        h = hashlib.sha256(vk.encode()).digest()[:16]
        did_suffix = base64.urlsafe_b64encode(h).decode("ascii").rstrip("=")
        did = f"did:agora:{did_suffix}"
        return cls(did=did, signing_key=sk, verify_key=vk)

    def did_document(self, endpoint_url: str | None = None) -> dict:
        """W3C DID-document for this identity."""
        doc: dict = {
            "@context": ["https://www.w3.org/ns/did/v1"],
            "id": self.did,
            "verificationMethod": [
                {
                    "id": f"{self.did}#key-1",
                    "type": "Ed25519VerificationKey2020",
                    "controller": self.did,
                    "publicKeyMultibase": self.public_key_multibase,
                }
            ],
        }
        if endpoint_url:
            doc["service"] = [
                {
                    "id": f"{self.did}#agora",
                    "type": "AgoraAgentEndpoint",
                    "serviceEndpoint": endpoint_url,
                }
            ]
        return doc
