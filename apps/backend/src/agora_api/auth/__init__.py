"""Authentication subsystem — Privy-backed user auth (Sprint 10d)."""

from .privy import (
    PrivyAuthError,
    get_current_user,
    get_current_user_optional,
    verify_privy_jwt,
)

__all__ = [
    "PrivyAuthError",
    "get_current_user",
    "get_current_user_optional",
    "verify_privy_jwt",
]
