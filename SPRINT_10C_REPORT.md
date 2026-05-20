# Sprint 10c — Marketplace Buy Flow

**Date:** 2026-05-20 (continuation)
**Goal:** make the "Buy with USDC" button on agoraproto.org/marketplace
actually buy something — using the existing x402 escrow plus a
listing-aware delivery endpoint.

## What landed

### Backend

| Change | Why |
|---|---|
| `Job.listing_id` column + Migration 0007 | Links an on-chain Job back to the marketplace Listing it originates from. FK to listings; nullable so existing flows are unaffected. |
| `X402JobRequest.listing_id` optional field | Buyers passing this field cause the resulting Job row to carry the link. |
| `_job_view()` exposes `listing_id` | UI can render "this is a marketplace purchase" badges later. |
| Auto-increment `listing.sales_count` | On successful `approveAndPay`, if the Job is linked to a Listing, bump that Listing's sales counter. |
| `GET /v1/listings/{id}/delivery?job_id=...` | The actual deliverable release. For digital products, returns `digital_content` as soon as the linked Job is in `offered` status (escrow funded). For services, returns `job.result` once the provider has submitted. Authorisation today: knowledge of the (listing_id, job_id) pair — Sprint 10d swaps in proper Privy auth. |

### Frontend

`apps/website/marketplace.html` got a full **purchase wizard** inside
the listing modal. Five steps:

1. **Pre-flight info** — what the buyer needs (Sepolia ETH, Sepolia USDC, an EVM wallet, a registered DID).
2. **Get payment instructions** — clicks the API, fetches the 402 challenge with the listing-aware body. No funds move.
3. **Broadcast on-chain** — copy-paste-ready `cast send` commands for the `approve` and `createJob` transactions, with all addresses, amounts, and the taskHash pre-filled.
4. **Submit tx hash** — input field for the `createJob` tx hash. The wizard posts back to `/v1/x402/jobs` with `X-Payment-Tx`, verifies on-chain, mirrors the Job in the DB.
5. **Deliver** — automatically fetches `/v1/listings/{id}/delivery?job_id=...` and shows the deliverable inline (Markdown / JSON / plain text formatted correctly).

The wizard tracks step state visually (pending → active → done) with
colored circles. Error states are shown inline per step. Copy buttons
on every code block. Reusable: each modal-open resets the wizard
cleanly so a different listing starts fresh.

**Buyer identity:** for Sprint 10c the wizard uses the hard-coded
`alice-demo` DID (`did:agora:4mrYSXT_f69BiaSeo7vmaA`) as the buyer. That
DID is seeded since Sprint 5. Sprint 10d will replace this with
Privy-backed per-user DIDs.

### Tests

`tests/test_listings.py` got three more cases:

- `test_delivery_unknown_listing` — 404 path
- `test_delivery_bad_uuid` — 400 path
- `test_delivery_releases_digital_content` — happy path: Listing created via API + Job inserted via DB session + delivery endpoint returns the `digital_content`
- `test_delivery_rejects_unlinked_job` — security: if `job.listing_id` doesn't match the URL listing, refuse (don't leak someone else's purchase)

## What this is NOT yet

- **No browser wallet integration** — the wizard tells the buyer the cast commands; the buyer copies them into their own terminal. Sprint 10c-2 (or later) would integrate MetaMask / WalletConnect so the wizard signs in-browser.
- **No buyer auth** — anyone can hit `/v1/listings/{id}/delivery` with a `(listing_id, job_id)` pair and get the content. The pair is functionally a bearer token because `job_id` is UUID. Sprint 10d's Privy auth will tighten this so only the actual buyer can retrieve.
- **No service-listing UI** — service listings have a `service_input_schema` the buyer must fill in. The wizard currently treats services the same as products at the on-chain layer (creates the Job), but doesn't render a schema-driven form for the buyer to fill task_spec. Until a real provider is wired up the schema is mostly aesthetic anyway.
- **No on-chain refund/approve UI** — once the Job is created, the wizard shows the delivery. A "Release escrow" button calling `/v1/x402/jobs/{id}/approve` is a natural next addition but not in 10c.

## How to deploy

```powershell
# Windows
cd C:\Users\WAVO\Desktop\Projekte\agor
git add apps/backend/alembic/versions/0007_jobs_link_listing.py `
        apps/backend/src/agora_api/db/models.py `
        apps/backend/src/agora_api/routes/listings.py `
        apps/backend/src/agora_api/routes/x402.py `
        apps/backend/tests/test_listings.py `
        apps/website/marketplace.html `
        SPRINT_10C_REPORT.md
git commit -m "feat(sprint-10c): buy flow — listing-aware x402 + delivery + UI wizard"
git push
```

```bash
# Server
ssh root@188.245.39.250
cd /opt/agora && git pull
cd apps/backend
source .venv/bin/activate
alembic upgrade head      # runs 0007
systemctl restart agora-api
sleep 3
systemctl status agora-api --no-pager | head -8

# Sanity: delivery endpoint exists in OpenAPI
curl -s https://api.agoraproto.org/v1/openapi.json | python3 -c "
import sys, json
d = json.load(sys.stdin)
paths = [p for p in d.get('paths', {}) if 'delivery' in p]
print(paths)
"
```

After that the marketplace UI buy flow is live. Visit
<https://agoraproto.org/marketplace.html>, click any listing, click
"Buy with USDC", walk through the wizard.

## Status

```
Sprint 10a  ✅ Listing model + API + seed
Sprint 10b  ✅ Marketplace browse UI
Sprint 10c  ✅ Buy flow (this sprint)
Sprint 10d  ⏳ Human-seller onboarding (Privy auth + create-listing UI)
```
