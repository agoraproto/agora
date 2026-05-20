# Sprint 10a — Marketplace foundation (Listing model + API)

**Date:** 2026-05-20 (continuation)
**Direction shift:** From "agent-first protocol demo" → "hybrid
marketplace for digital products + AI services where both agents and
humans can sell, USDC-settled."

## What landed

### 1. `Listing` data model (`apps/backend/src/agora_api/db/models.py`)

Three enums: `ListingKind` (`agent` / `user`), `ListingType` (`service`
/ `digital_product`), `ListingStatus` (`active` / `paused` /
`archived`). One `Listing` table with the fields below.

**Why one table for both kinds:** services and digital products share
seller, pricing, presentation, stats — only the "what gets delivered"
half is different. Service listings reference a capability tag + a
buyer-input JSON schema; digital-product listings carry the
deliverable in `digital_content`. The discriminator (`listing_type`)
keeps the two paths apart at the API layer.

**Why `seller_did` is a string, not a foreign key:** the marketplace
allows both agents and humans to sell. Rather than UNION two FK
columns, we store the DID as a varchar and the API validates that the
target exists (strict for agents today, permissive for users until
Sprint 10d adds Privy-backed user records).

**What's intentionally NOT in the public response:** `digital_content`.
That's the paid deliverable; releasing it to anyone who can hit
`GET /v1/listings/{id}` would be the worst kind of bug. Sprint 10c
(buy flow) will release `digital_content` only after a successful
on-chain payment is verified.

### 2. Migration 0006 (`apps/backend/alembic/versions/0006_marketplace_listings.py`)

Creates the `listings` table with the indexes the search route needs
(`seller_did`, `seller_kind`, `listing_type`, `category`, `status`).

### 3. Repository (`apps/backend/src/agora_api/db/listings_repo.py`)

`create()`, `get()`, `search()` (with category / type / seller /
free-text / max-price / pagination filters), `archive()`,
`increment_sales()`, plus `to_public_dict()` which strips
`digital_content` from the response.

### 4. API routes (`apps/backend/src/agora_api/routes/listings.py`)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/listings` | Create a listing (rate-limited 30/min). Validates seller_kind, listing_type, that agent sellers exist, that service listings have a capability and digital products have content. |
| `GET` | `/v1/listings` | Browse — filter by category, listing_type, seller_kind, seller_did, free-text `q`, `max_price`. Default sort: most sales first, then newest. Pagination via `limit` (1..200) + `offset`. |
| `GET` | `/v1/listings/{id}` | Fetch a single listing (404 if archived listings are hidden from the default list but still resolvable by id). |
| `DELETE` | `/v1/listings/{id}` | Soft-delete (sets status → archived). No auth check yet — Sprint 10d locks this down. |

Wired into `main.py` under `prefix="/v1/listings"`, tag `marketplace`.

### 5. Seed script (`scripts/seed_listings.py`)

Five sample listings:

- **`Cold-email opener pack`** — digital product, user-sold, 1.50 USDC
- **`German legal-NER training set`** — digital product, user-sold, 12.00 USDC
- **`Custom GPT: senior product designer`** — digital product, user-sold, 0.75 USDC
- **`Echo as a service`** — service, agent-sold (echo-agent-demo), 0.50 USDC
- **`Translation EN→DE formal`** — service, agent-sold (echo-agent-demo), 0.80 USDC

Run with:
```bash
AGORA_BASE_URL=https://api.agoraproto.org python3 scripts/seed_listings.py
```

(Or `http://127.0.0.1:8000` against local dev.)

### 6. Tests (`apps/backend/tests/test_listings.py`)

14 pytest cases covering:

- Create service / create product
- Validation: service requires capability, product requires content
- Unknown agent seller rejected (400)
- List with filters (type / category / seller_kind / max_price)
- Free-text search hits title + description
- Get by id (200 / 404 / 400)
- Archive flow + hidden from default browse
- Negative price rejected
- Bad seller_kind rejected
- Pagination respects `limit`

## What this is NOT yet

- **No marketplace UI** — Sprint 10b adds `apps/website/marketplace.html`
  with an Etsy-style grid.
- **No buy flow** — Sprint 10c routes a "Buy" button through the
  existing `/v1/x402/jobs` flow and releases `digital_content` on
  approval.
- **No human seller onboarding** — Sprint 10d wires Privy auth + a
  listing-creation UI for human sellers.
- **`digital_content` is currently writable by anyone via `POST`** —
  testnet / dev only. Sprint 10d adds the auth layer that locks
  POST/DELETE to verified sellers.

## How to deploy

```powershell
# Windows
cd C:\Users\WAVO\Desktop\Projekte\agor
git add apps/backend/src/agora_api/db/models.py `
        apps/backend/src/agora_api/db/listings_repo.py `
        apps/backend/src/agora_api/routes/listings.py `
        apps/backend/src/agora_api/main.py `
        apps/backend/alembic/versions/0006_marketplace_listings.py `
        apps/backend/tests/test_listings.py `
        scripts/seed_listings.py `
        SPRINT_10A_REPORT.md
git commit -m "feat(sprint-10a): marketplace Listing model + API + seed"
git push
```

```bash
# Server
ssh root@188.245.39.250
cd /opt/agora && git pull
cd apps/backend
source .venv/bin/activate

# Migrate
alembic upgrade head      # runs 0006

# Restart so the new route is mounted
systemctl restart agora-api
sleep 3

# Seed 5 listings against the live API
python3 ../../scripts/seed_listings.py
# (env var defaults to localhost; explicitly:)
#   AGORA_BASE_URL=https://api.agoraproto.org python3 ../../scripts/seed_listings.py

# Smoke test
curl -s https://api.agoraproto.org/v1/listings | python3 -m json.tool | head -40
```

After that the `/v1/listings` endpoint is live and seeded, ready for
Sprint 10b's UI to fetch from.

## Status

```
Sprint 10a  ✅ done   — Listing model + API + seed + tests
Sprint 10b  ⏳ next   — Marketplace UI at agoraproto.org/marketplace
Sprint 10c  ⏳        — Buy flow (digital_content delivery on approval)
Sprint 10d  ⏳        — Privy-auth for human sellers + creation UI
```
