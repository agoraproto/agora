"""Rate limiting via slowapi.

Used to prevent abuse on write-heavy endpoints (agent registration, job
creation, dispute opening). Read endpoints are intentionally NOT limited so
agents and AI crawlers can browse freely.

Defaults are soft - bootstrap-friendly. Tune `Settings.rate_limit_*`
to tighten if abuse appears.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import get_settings

_settings = get_settings()


def _key_func(request) -> str:  # type: ignore[no-untyped-def]
    """Use the client IP as the limit bucket.

    Trusts X-Forwarded-For when present (set by Caddy in our deployment).
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=_key_func,
    default_limits=[],  # no global default; per-route opt-in via decorators
    enabled=_settings.rate_limit_enabled,
)
