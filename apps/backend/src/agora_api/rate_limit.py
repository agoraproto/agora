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
    """Use the client IP as the rate-limit bucket.

    M-05 audit fix: previously the function trusted any X-Forwarded-For
    header blindly and used the FIRST entry — which is attacker-controllable
    (anyone can set their own XFF and pick their own bucket). Now:

    1) Only trust XFF when explicitly enabled (`settings.trust_forwarded_for`,
       default off). In local dev with no reverse proxy, get_remote_address
       is correct.
    2) When trusted, take the LAST entry in the XFF chain (the one closest
       to our edge proxy, the only one we can actually verify by virtue of
       receiving it on the loopback). Caddy appends its own client view as
       the last hop, so this is the proxy's own observation.
    """
    trust_xff = bool(getattr(_settings, "trust_forwarded_for", False))
    if trust_xff:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                return parts[-1]
    return get_remote_address(request)


limiter = Limiter(
    key_func=_key_func,
    default_limits=[],  # no global default; per-route opt-in via decorators
    enabled=_settings.rate_limit_enabled,
)
