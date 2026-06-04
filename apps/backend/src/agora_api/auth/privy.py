"""Privy JWT verification + FastAPI auth dependencies (Sprint 10d).

Privy issues a short-lived ES256-signed JWT for every authenticated
session. The frontend passes it to our backend as
`Authorization: Bearer <token>`. We:

  1. Fetch and cache Privy's JWKS for our app
     (`https://auth.privy.io/api/v1/apps/{app_id}/jwks.json`).
  2. Verify the token signature, issuer (`privy.io`), audience
     (= our `PRIVY_APP_ID`), and expiry.
  3. Resolve `sub` (Privy user id) to an Agora `User` row, creating it
     on the fly if it's the user's first login.

The dependency `get_current_user(...)` returns a tuple `(User, Agent)`
where `Agent` is the user's personal agent (the one the marketplace
uses as `requester_did` / `seller_did`). Routes that need auth declare
it like:

    @router.post("/sell")
    async def sell(
        body: SellBody,
        principal: tuple[User, Agent] = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ):
        user, agent = principal
        ...

**Test mode:** when `PRIVY_APP_ID` is empty (local dev / pytest), the
verifier accepts an unsigned dev token of the form
`agora-dev:<privy_user_id>` so test cases can simulate auth without
talking to Privy. This branch is only reachable when the env var is
absent, so production stays strict.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import users_repo
from ..db.base import get_session
from ..db.models import Agent, User

# ──────────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────────


class PrivyAuthError(HTTPException):
    """401-shaped error with a WWW-Authenticate hint."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


# ──────────────────────────────────────────────────────────────────
# JWKS cache
# ──────────────────────────────────────────────────────────────────


@dataclass
class _JwksCache:
    keys: list[dict[str, Any]]
    fetched_at: float


_JWKS_TTL_SECONDS = 600.0
_jwks_cache: _JwksCache | None = None


async def _fetch_jwks(app_id: str) -> list[dict[str, Any]]:
    """Fetch the JWKS for our Privy app; cached for 10 minutes."""
    global _jwks_cache
    now = time.time()
    if _jwks_cache is not None and now - _jwks_cache.fetched_at < _JWKS_TTL_SECONDS:
        return _jwks_cache.keys

    url = f"https://auth.privy.io/api/v1/apps/{app_id}/jwks.json"
    async with httpx.AsyncClient(timeout=5.0) as http:
        r = await http.get(url)
        r.raise_for_status()
        data = r.json()
    keys = data.get("keys") or []
    if not keys:
        raise PrivyAuthError("Privy JWKS endpoint returned no keys")
    _jwks_cache = _JwksCache(keys=keys, fetched_at=now)
    return keys


def _key_for_kid(keys: list[dict[str, Any]], kid: str | None) -> dict[str, Any]:
    if kid is None:
        # If the token has no kid, the JWKS has to be single-key.
        if len(keys) == 1:
            return keys[0]
        raise PrivyAuthError("token missing 'kid' header and JWKS has multiple keys")
    for k in keys:
        if k.get("kid") == kid:
            return k
    raise PrivyAuthError(f"no JWKS entry for kid={kid!r}")


# ──────────────────────────────────────────────────────────────────
# Token verification
# ──────────────────────────────────────────────────────────────────


async def verify_privy_jwt(token: str) -> dict[str, Any]:
    """Verify a Privy JWT and return its decoded claims.

    Raises `PrivyAuthError` on any failure.
    """
    settings = get_settings()

    # ── Dev / test escape hatch (Sprint 39 / B-V2-01 hardened) ──
    # The dev-bearer path accepts `agora-dev:<uid>` tokens and synthesises
    # the Privy claims for them. Pre-Sprint-39 this was gated implicitly by
    # `PRIVY_APP_ID == ""`, which was a fail-open posture: any deployment
    # that lost the env var would silently re-enable the bypass.
    #
    # Now: BOTH the explicit `ALLOW_DEV_BEARER=true` flag AND an empty
    # `PRIVY_APP_ID` are required. Production sets neither; tests / local
    # dev set both.
    if settings.allow_dev_bearer and not settings.privy_app_id:
        if token.startswith("agora-dev:"):
            privy_user_id = token.removeprefix("agora-dev:").strip()
            if not privy_user_id:
                raise PrivyAuthError("dev token missing privy user id")
            return {"sub": privy_user_id, "iss": "agora-dev", "aud": "agora-dev"}
        raise PrivyAuthError(
            "Privy auth not configured on this server (set PRIVY_APP_ID)"
        )
    if not settings.privy_app_id:
        # PRIVY_APP_ID not set AND allow_dev_bearer not explicitly enabled.
        # Refuse to authenticate anything — fail-closed posture.
        raise PrivyAuthError(
            "Privy auth not configured (PRIVY_APP_ID empty, ALLOW_DEV_BEARER not set)"
        )

    # ── Real verification path ──
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise PrivyAuthError(f"malformed JWT header: {e}") from e

    keys = await _fetch_jwks(settings.privy_app_id)
    jwk = _key_for_kid(keys, header.get("kid"))
    try:
        public_key = jwt.algorithms.ECAlgorithm.from_jwk(jwk)  # type: ignore[attr-defined]
    except Exception as e:
        raise PrivyAuthError(f"could not parse JWK: {e}") from e

    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            audience=settings.privy_app_id,
            issuer="privy.io",
            options={"require": ["sub", "iss", "aud", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise PrivyAuthError("token expired") from e
    except jwt.InvalidAudienceError as e:
        raise PrivyAuthError("token audience mismatch") from e
    except jwt.InvalidIssuerError as e:
        raise PrivyAuthError("token issuer mismatch") from e
    except jwt.PyJWTError as e:
        raise PrivyAuthError(f"invalid token: {e}") from e

    if not claims.get("sub"):
        raise PrivyAuthError("token missing 'sub' claim")
    return claims


# ──────────────────────────────────────────────────────────────────
# FastAPI dependencies
# ──────────────────────────────────────────────────────────────────


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> tuple[User, Agent]:
    """Require a valid Privy session. Returns (User, personal Agent).

    Auto-upserts the User+Agent on first login. Hints for the frontend:
    additional `X-Privy-Email` and `X-Privy-Wallet` request headers, if
    present, are propagated into the User row (Privy's JWT itself only
    carries `sub`, so the SDK forwards these out-of-band on the sync
    call so we can populate the profile).
    """
    token = _extract_bearer(request)
    if not token:
        raise PrivyAuthError("missing Authorization: Bearer <token>")
    claims = await verify_privy_jwt(token)
    privy_user_id = claims["sub"]

    email = request.headers.get("X-Privy-Email") or None
    wallet = request.headers.get("X-Privy-Wallet") or None

    user, agent = await users_repo.upsert_from_privy(
        session,
        privy_user_id=privy_user_id,
        email=email,
        primary_wallet=wallet,
    )
    await session.commit()
    return user, agent


async def get_current_user_optional(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> tuple[User, Agent] | None:
    """Like get_current_user but returns None when no Authorization header is sent.

    Useful for endpoints that personalise the response when logged in but
    still work anonymously (e.g. `/v1/listings` listing search).
    """
    if _extract_bearer(request) is None:
        return None
    return await get_current_user(request, session)
