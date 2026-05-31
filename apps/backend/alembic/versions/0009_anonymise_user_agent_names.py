"""Sprint 26 — scrub email addresses from user-agent display names.

CRITICAL privacy fix. Up to Sprint 26 a Privy-email login persisted the
raw email address as the public agent name (visible on dashboard.agora-
proto.org, indexable by search engines). That violates GDPR Art. 5(1)(c)
data minimisation and exposed at least three real addresses in the wild:

    herberge.taube@gmail.com
    andreas-buyer@test.de
    aw2012@web.de

The code path (apps/backend/src/agora_api/db/users_repo.py) is fixed
forward in the same sprint. This migration rewrites any already-existing
row whose `name` field looks like an email address into the anonymised
`User <first-8-of-did>` pattern that was already used as fallback.

Heuristic: name LIKE '%@%.%' AND type = 'user'. We don't try to be smart
about uncommon TLDs — anything matching that pattern on a user-type
agent is rewritten. Worst case we anonymise a benign name; that's still
the right outcome.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite + Postgres both support split-and-substring via SQL but the
    # exact functions differ. Easiest cross-engine path: load rows, rewrite
    # in Python, push back.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT did, name FROM agents "
            "WHERE type = 'user' AND name LIKE '%@%.%'"
        )
    ).fetchall()

    rewrites = 0
    for did, _name in rows:
        # Same algorithm as the code path: 'User ' + first 8 chars of the
        # last DID segment (e.g. did:agora:c7BacdGCbX7NP-iKntR8nQ -> 'User c7BacdGC').
        suffix = did.rsplit(":", 1)[-1][:8] if did else "anon"
        new_name = f"User {suffix}"
        conn.execute(
            sa.text("UPDATE agents SET name = :n WHERE did = :d"),
            {"n": new_name, "d": did},
        )
        rewrites += 1

    if rewrites:
        # Print so the deploy log shows what we did (Alembic shows op output)
        print(f"[migration 0009] anonymised {rewrites} agent name(s) "
              f"that contained an email address")


def downgrade() -> None:
    # No-op. We cannot recover the original email from the anonymised
    # handle (we deliberately threw it away). Downgrading the schema is
    # safe; the data simply stays anonymised — which is the desired
    # state anyway.
    pass
