"""Sponsor signature verification (ADR 007 — Anti-Sybil).

ADR 007 lets a new agent bypass the stake-based bootstrapping tier by
getting a signed pledge from an already-established agent. The
established ("sponsor") agent risks part of their stake if the sponsored
agent misbehaves within the first 90 days, and earns a small cut of
that agent's platform fee in return.

This module owns the *verification* half of that mechanism: at
registration time, did the alleged sponsor actually sign a pledge for
this exact new agent, and does that sponsor qualify to vouch?

The economic half — slashing on misbehaviour, distributing the 5 %
reward — is a separate concern and not implemented here yet (Sprint 9h).
The data needed for those flows (sponsor_did + sponsor_signature on the
Agent row) is already persisted, so the slashing logic can be bolted on
later without touching this verification layer.

Canonical signing payload:

    {
        "agora_sponsor_version": 1,
        "new_agent_did": "<the new agent's DID>",
        "sponsor_did":   "<the sponsor's DID>",
        "stake_pledged": "5.00",          # decimal string, EUR
        "valid_until_unix": 1796000000     # int, seconds since epoch
    }

…serialized with sort_keys=True, separators=(",", ":"), UTF-8 encoded,
signed with the sponsor's Ed25519 private key. The corresponding public
key is recovered from `sponsor.did_document.verificationMethod[].publicKeyMultibase`.

Same canonicalisation as `_task_hash` in routes/x402.py — this matters
because off-line tooling (SDKs, MCP server) needs to reproduce exactly
these bytes to be able to sign in the first place.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from .db.models import Agent, TrustLevel

# ADR 007 thresholds. Centralised so tests + docs see the same numbers.
_ELIGIBLE_TRUST: tuple[TrustLevel, ...] = (TrustLevel.verified, TrustLevel.trusted)
_MIN_JOBS_COMPLETED = 50


class SponsorshipInvalid(Exception):
    """Raised when a presented sponsor signature can't be honoured.

    Catch this at the registration boundary and translate to HTTP 400 —
    the new agent simply has to register without a sponsor (and then
    fall back to the stake-based tier).
    """


def canonical_sponsor_payload(
    *,
    new_agent_did: str,
    sponsor_did: str,
    stake_pledged: str,
    valid_until_unix: int,
) -> bytes:
    """Bytes a sponsor signs when issuing a pledge.

    Returned bytes are deterministic — same inputs always yield same
    output — so client tooling can reproduce them off-line without
    talking to the server.
    """
    return json.dumps(
        {
            "agora_sponsor_version": 1,
            "new_agent_did": new_agent_did,
            "sponsor_did": sponsor_did,
            "stake_pledged": stake_pledged,
            "valid_until_unix": valid_until_unix,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


# Minimal base58btc decoder — used to unwrap publicKeyMultibase strings
# from the sponsor's DID document. Avoids adding an extra dependency for
# this single utility.
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {ch: i for i, ch in enumerate(_B58_ALPHABET)}


def _b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        if ch not in _B58_INDEX:
            raise SponsorshipInvalid(f"publicKeyMultibase contains non-base58 char {ch!r}")
        n = n * 58 + _B58_INDEX[ch]
    leading_zero_count = 0
    for ch in s:
        if ch == "1":
            leading_zero_count += 1
        else:
            break
    body_len = (n.bit_length() + 7) // 8
    body = n.to_bytes(body_len, "big") if body_len else b""
    return b"\x00" * leading_zero_count + body


def extract_verify_key_from_did_document(doc: dict[str, Any]) -> VerifyKey:
    """Pull the first Ed25519 public key out of a DID document.

    Supports both `Ed25519VerificationKey2020` (current) and the older
    `Ed25519VerificationKey2018` shape. Accepts the multibase prefixed
    `0xed 0x01` multicodec form (current convention) and a bare 32-byte
    form (older / SDK-internal docs).
    """
    if not isinstance(doc, dict):
        raise SponsorshipInvalid("DID document is missing or not a JSON object")
    methods = doc.get("verificationMethod", [])
    if not isinstance(methods, list):
        raise SponsorshipInvalid("verificationMethod is not a list")
    for vm in methods:
        if not isinstance(vm, dict):
            continue
        if vm.get("type") not in (
            "Ed25519VerificationKey2020",
            "Ed25519VerificationKey2018",
        ):
            continue
        multibase = vm.get("publicKeyMultibase")
        if not isinstance(multibase, str) or not multibase.startswith("z"):
            continue
        raw = _b58decode(multibase[1:])
        # Multicodec prefix for ed25519-pub is 0xed 0x01 (LEB128 of 0xed).
        if len(raw) >= 34 and raw[0] == 0xED and raw[1] == 0x01:
            return VerifyKey(raw[2:34])
        if len(raw) == 32:
            return VerifyKey(raw)
    raise SponsorshipInvalid("no Ed25519 verificationMethod in sponsor's DID document")


def check_eligibility(sponsor: Agent) -> None:
    """Raise SponsorshipInvalid if `sponsor` is not allowed to vouch.

    Per ADR 007: trust_level must be verified or trusted, and the
    sponsor must have at least 50 completed jobs. This is what makes
    the mechanism Sybil-resistant — a fresh agent can't bootstrap
    other fresh agents.
    """
    trust = sponsor.trust_level
    # Some sessions hand us the raw enum, some the .value string — be
    # permissive about both.
    trust_val = trust.value if hasattr(trust, "value") else str(trust)
    if trust_val not in {t.value for t in _ELIGIBLE_TRUST}:
        raise SponsorshipInvalid(
            f"sponsor trust_level={trust_val} not eligible; "
            f"need one of {[t.value for t in _ELIGIBLE_TRUST]}"
        )
    if sponsor.jobs_completed < _MIN_JOBS_COMPLETED:
        raise SponsorshipInvalid(
            f"sponsor has only {sponsor.jobs_completed} completed jobs; "
            f"need at least {_MIN_JOBS_COMPLETED} per ADR 007"
        )


def verify_signature(
    *,
    sponsor: Agent,
    new_agent_did: str,
    stake_pledged: str,
    valid_until_unix: int,
    signature_b64: str,
) -> None:
    """Verify a sponsor signature over the canonical pledge.

    Raises SponsorshipInvalid on any mismatch — bad base64, missing key
    in DID document, signature mismatch. On success returns None.
    """
    try:
        sig = base64.b64decode(signature_b64)
    except Exception as e:
        raise SponsorshipInvalid(f"signature is not valid base64: {e}") from e
    payload = canonical_sponsor_payload(
        new_agent_did=new_agent_did,
        sponsor_did=sponsor.did,
        stake_pledged=stake_pledged,
        valid_until_unix=valid_until_unix,
    )
    verify_key = extract_verify_key_from_did_document(sponsor.did_document or {})
    try:
        verify_key.verify(payload, sig)
    except BadSignatureError as e:
        raise SponsorshipInvalid("sponsor signature does not match the canonical payload") from e
