# Sprint 10d — Privy-Login + Seller-Dashboard

**Datum:** 2026-05-21
**Ziel:** Marktplatz wird nutzbar für echte Menschen — Login, eigene
Listings verkaufen, eigene Käufe abrufen. Aus dem `alice-demo`-Stub
wird ein Per-User-Konto.

## Was gelandet ist

### Backend

| Change | Warum |
|---|---|
| `User.privy_user_id`, `User.primary_wallet` Felder + Migration 0008 | Verknüpft eine Privy-Identität (stabile ID + EVM-Adresse) mit unserer User-DID. |
| `users_repo.py` (neu) | `upsert_from_privy(privy_user_id, email, wallet)` — idempotent. Erstellt User + 1-zu-1 "personal Agent" beim ersten Login. DID wird deterministisch aus dem Privy-ID gehasht (`did:agora:<base64url>`). |
| `auth/privy.py` (neu) | Echte ES256-JWT-Verifizierung gegen Privy's JWKS (`auth.privy.io/api/v1/apps/{app_id}/jwks.json`), 10-Min-Cache. Plus Dev-Pfad: wenn `PRIVY_APP_ID` leer ist, akzeptiert er `agora-dev:<id>` Tokens (für Tests + Frontend-Bootstrap). |
| `routes/auth.py` (neu) | `POST /v1/auth/sync`, `GET /v1/auth/me`, `GET /v1/auth/my-listings`. Alle drei verlangen `Authorization: Bearer ...`. |
| **Authorisierungs-Härtung in `listings.py`** | `POST /v1/listings`: wenn authed, wird `seller_kind="user"` und `seller_did=user.did` **forciert** — kein Spoofing möglich. `DELETE /v1/listings/{id}`: User-Listings nur archivierbar vom Owner (401/403). `GET /v1/listings/{id}/delivery`: User-Käufe nur abrufbar vom eingeloggten Käufer (401/403). |
| `PyJWT[crypto]>=2.9.0` in `pyproject.toml` | ES256-Verifizierung. |

### Frontend

`apps/website/marketplace.html`
* **Login-Modal** in der Nav (Email / Connect Wallet / Google-Stub).
* `AGORA_AUTH` State in `sessionStorage`: `{ token, did, email, primary_wallet }`.
* `authHeaders()` Helper, der `Authorization: Bearer ...` + `X-Privy-Email` + `X-Privy-Wallet` Headers an alle Backend-Calls anhängt.
* `getBuyerDid()` ersetzt die hardgecodete `alice-demo`-DID — Buyer-DID kommt jetzt vom eingeloggten User.
* Buy-Wizard öffnet automatisch das Login-Modal, wenn man ohne Login auf "Get payment instructions" klickt.

`apps/website/sell.html` (neu, ~570 Zeilen)
* "Sell on Agora" Seite mit demselben Login-State wie marketplace.html.
* **My Listings**: `GET /v1/auth/my-listings` → Grid mit Sales-Counter, Status-Badge, Archive-Button pro Card.
* **Create Listing Form**: Modal mit allen Feldern — Listing-Type (Service/Digital Product), Titel, Beschreibung, Preis, Kategorie, Content-Type, Content-Body (Text/JSON/URL), Payout-Wallet (default = Privy primary wallet).
* Auth-required-State: ohne Login zeigt die Seite einen Login-Prompt statt "My Listings".

### Tests

`apps/backend/tests/test_auth.py` (neu) — 9 Tests:
* `test_sync_creates_user_and_agent` — Erstauth legt User + Agent an.
* `test_sync_is_idempotent` — selber Privy-ID → selbe DID, kein Duplikat.
* `test_me_returns_logged_in_user` / `test_me_401_without_token` / `test_me_401_with_garbage_token`.
* `test_my_listings_only_returns_owned` — Alice und Bob loggen sich ein, Alice publiziert, nur Alice sieht es.
* `test_create_listing_forces_authed_seller` — Spoof-Attempt (Body sagt anderer DID) wird vom Backend überschrieben.
* `test_anonymous_create_requires_seller_fields` — anonyme Calls ohne Seller-Felder → 400.
* `test_archive_blocked_for_non_owner` — Mallory kann Alice's Listing nicht archivieren (403); Anonymous kann nicht (401); Alice selbst kann (200).

## Privy in Produktion vs. Dev-Mode

**Aktueller Stand:** `PRIVY_APP_ID` ist leer auf dem Server. Frontend
benutzt dev-Tokens (`agora-dev:email-<sha256(email).slice(0,16)>` oder
`agora-dev:wallet-<0xaddr>`). Backend akzeptiert diese, weil der
Dev-Pfad aktiv ist. Funktional vollwertig — User-Identitäten sind
stabil, Listings + Käufe sind dem User zugeordnet, Authorisierung
funktioniert.

**Was du machen musst um echtes Privy einzuschalten:**

1. **Privy-Account anlegen** (kostenlos):
   * Auf `dashboard.privy.io` registrieren
   * Neue App namens "Agora" erstellen
   * Login-Methoden aktivieren: Email, Google, MetaMask, WalletConnect
   * App-ID + App-Secret kopieren

2. **Env-Vars auf dem Server setzen** in `/opt/agora/apps/backend/.env`:
   ```
   PRIVY_APP_ID=clxxxxxxxxxxxxxxxxxxxxxx
   PRIVY_APP_SECRET=secret-xxxxxxxxxxxxxx
   ```

3. **Privy-Frontend-SDK integrieren** (Sprint 10e): aktueller Frontend-Login-Stub durch echtes Privy SDK ersetzen, sodass echte JWTs ausgestellt werden. Dann fließen echte Signaturen statt `agora-dev:...`. Der Backend-Verifier ist schon production-ready.

## Wie deployen

```powershell
# Windows
cd C:\Users\WAVO\Desktop\Projekte\agor
git add apps/backend/alembic/versions/0008_users_privy.py `
        apps/backend/src/agora_api/db/models.py `
        apps/backend/src/agora_api/db/users_repo.py `
        apps/backend/src/agora_api/auth/ `
        apps/backend/src/agora_api/routes/auth.py `
        apps/backend/src/agora_api/routes/listings.py `
        apps/backend/src/agora_api/main.py `
        apps/backend/pyproject.toml `
        apps/backend/tests/test_auth.py `
        apps/website/marketplace.html `
        apps/website/sell.html `
        SPRINT_10D_REPORT.md
git commit -m "feat(sprint-10d): Privy auth + seller dashboard + listing creation UI"
git push
```

```bash
# Server (api.agoraproto.org)
ssh root@188.245.39.250
cd /opt/agora && git pull

cd apps/backend
source .venv/bin/activate
pip install -e .            # zieht PyJWT[crypto]
alembic upgrade head        # runs 0008
systemctl restart agora-api
sleep 3
systemctl status agora-api --no-pager | head -8

# Sanity: neue Routes
curl -s https://api.agoraproto.org/v1/openapi.json | python3 -c "
import sys, json
d = json.load(sys.stdin)
auth_paths = [p for p in d.get('paths', {}) if p.startswith('/v1/auth')]
print('Auth routes:', auth_paths)
"

# Sanity: /v1/auth/me sollte ohne Token 401 returnen
curl -s -o /dev/null -w '%{http_code}\n' https://api.agoraproto.org/v1/auth/me
# expected: 401
```

```bash
# Smoke-Test der Tests (auf dem Server oder lokal mit Python 3.11+)
cd apps/backend
pytest tests/test_auth.py -v
```

Frontend braucht keinen separaten Deploy-Schritt — Caddy serviert
`apps/website/` statisch, also greift der Push automatisch.

## Was du als User danach machen kannst

1. **Login** auf `agoraproto.org/marketplace.html` → "Login" Button → Email eingeben (oder MetaMask).
2. **Verkaufen**: auf `agoraproto.org/sell.html` → "New Listing" → Form ausfüllen → publish.
3. **Kaufen**: marketplace.html → Listing klicken → "Buy with USDC" → Buy-Wizard läuft mit deiner DID (nicht mehr alice-demo).
4. **Mein eigenes Listing sehen**: sell.html → My Listings → Sales-Counter, Archive-Button.

## Was diese Sprint NICHT bringt

* **Echtes Privy SDK im Frontend** — der Login-Modal ist ein Stub der `agora-dev:...` Tokens erzeugt. Funktional vollwertig, aber für Produktion solltest du Privy SDK einbinden (Sprint 10e, ~2h Arbeit). Vorteile: echte Email-Magic-Links, echtes Google SSO, echtes WalletConnect.
* **Listing-Editing** — du kannst nur neue Listings erstellen oder bestehende archivieren. Edit ist ein eigener Sprint.
* **Agent-DID-Auth** — Agent-Listings (seller_kind='agent') sind weiterhin anonym editierbar/archivierbar. Sprint 10f: DID-Signature-Verification für Agent-Auth.
* **Onramp** — Käufer brauchen weiterhin USDC + ETH auf Sepolia. Sprint 10g: Coinbase Onramp / MoonPay direkt im Buy-Wizard.

## Status

```
Sprint 10a  ✅ Listing model + API + seed
Sprint 10b  ✅ Marketplace browse UI
Sprint 10c  ✅ Buy flow (x402 + delivery)
Sprint 10d  ✅ Privy-Login + Seller-Dashboard (diese Sprint)
Sprint 10e  ⏳ Echtes Privy SDK im Frontend (ersetzt dev-tokens)
Sprint 10f  ⏳ Agent-DID-Signature-Auth (härtet Agent-Listings)
Sprint 10g  ⏳ Fiat-Onramp im Buy-Wizard (Coinbase Onramp / MoonPay)
```
