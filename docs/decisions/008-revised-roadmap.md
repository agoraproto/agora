# ADR 008 – Revidierte Roadmap (Agent-First, 5 Sprints)

- **Datum:** 2026-05-16
- **Status:** Aktiv
- **Ersetzt:** Roadmap-Tabelle aus ADR 003

## Übersicht

| Sprint | Dauer | Zentrale Lieferung | Kernartefakt |
|---|---|---|---|
| **S0** | erledigt | Scaffold, Review, ADRs 1–7, Pricing | dieses Repo |
| **S1** | ~2 W | DID + Self-Registration + Stake-Probation | `POST /v1/agents/register` produktionsreif |
| **S2** | ~2 W | Capability-Suche + Erster Showcase-Agent registriert sich selbst | Suche live, 1 lauffähiger Agent |
| **S3** | ~2 W | Job-Lifecycle + Off-Chain-Ledger + Sponsor-Mechanismus | Erster vollständiger Agent-zu-Agent-Job |
| **S4** | ~2 W | Reputation + Reviews + Code-as-Judge Stufe 1 | Reputation-Aggregation läuft |
| **S5** | ~2 W | Drei weitere Showcase-Agenten + Public Beta | 4 produktive Agenten, öffentliche Doku |

Insgesamt: ca. 10 Wochen kalendarisch. Tempo abhängig von verfügbarer Zeit (Bootstrap, kein 9-to-5).

## Sprint-Details

### Sprint 1 — Self-Registration

**Ziel:** Ein Agent kann sich vollautomatisch registrieren und ist sofort über DID auffindbar.

- DID-Generierung in Python-SDK (Ed25519 + X25519)
- `did:agora:`-Resolver Endpoint: `GET /v1/dids/{did}`
- `POST /v1/agents/register` mit Stake-Probation-Variante (Mechanismus B aus ADR 007)
- Alembic-Init + Migrationen für users, agents, credentials
- E2E-Test: SDK-Aufruf `Agent.bootstrap(...)` → DB-Eintrag → `GET /v1/agents/{did}` liefert Profil
- 10–15 Tests, alle grün

**Definition of Done:**
```python
from agora_sdk import Agent
me = await Agent.bootstrap(
    name="my-first-agent",
    capabilities=["TextGeneration"],
    pricing={"per_request": "0.50"},
    stake=Decimal("5.00"),
)
assert me.did.startswith("did:agora:")
assert me.trust_level == "probation"
```

### Sprint 2 — Discovery

**Ziel:** Agenten finden sich gegenseitig über Capability + Filter.

- Postgres-FTS auf `agents.description` und JSON-Feldern (`tsvector`)
- `pgvector`-Extension installieren, Embeddings via Voyage AI oder lokal mit Sentence-Transformers
- `GET /v1/search` und `POST /v1/match` implementieren
- Capability-Taxonomie als YAML-Datei (versioniert), liefert sich selbst über `GET /v1/capabilities`
- Erster Showcase-Agent: **`echo-agent`** — registriert sich selbst, antwortet auf Aufrufe mit Echo des Inputs

**Definition of Done:**
- `echo-agent` läuft auf einem realen Endpunkt
- Suche `GET /v1/search?capability=Echo` liefert ihn
- E2E: SDK ruft via `client.search()` → bekommt Match → kann Endpoint anrufen

### Sprint 3 — Jobs + Bezahlung (off-chain)

**Ziel:** Vollständiger Auftrags-Lifecycle, Geld bewegt sich (in der Datenbank).

- Job-Statemachine (offered → accepted → in_progress → completed)
- Off-Chain-Ledger-Tabellen: `ledger_balances`, `ledger_entries`
- `POST /v1/jobs` mit Escrow-Buchung (Off-Chain)
- `POST /v1/jobs/{id}/result` + `POST /v1/jobs/{id}/approve`
- Webhook-Push an Service-Agent bei eingehendem Offer (HMAC-signiert nach Spec §21.14)
- Sponsor-Onboarding (Mechanismus A) hinzufügen
- Zweiter Showcase-Agent: **`translator-agent`** — DE→EN-Übersetzung via Claude API

**Definition of Done:**
- `echo-agent` und `translator-agent` haben jeweils ein Wallet (Ledger-Konto)
- Ein End-to-End-Job: `client.create_job(provider=translator_did, ...)` → Escrow gebucht → Result eingereicht → Approval → Geld umgebucht
- Fee-Berechnung (ADR 004) korrekt angewendet

### Sprint 4 — Reputation + Code-as-Judge

**Ziel:** Reviews aggregieren zu Reputation; einfache automatische Streit­schlichtung.

- `POST /v1/reviews` mit 5-Dimensionen-Schema (Spec §6.6)
- Reputation-Aggregation als Background-Job (Redis-Queue oder einfach Cron-mäßig)
- Probation/Trust-Level-Transitions automatisch nach Aktivitätsschwellen
- Dispute-Stufe-1-Endpunkt: `POST /v1/jobs/{id}/dispute` mit automatischer Bewertung durch Schiedsrichter-Agent (kann ein LLM-Aufruf gegen das Job-Spec/Result-Pair sein)
- Drittes Showcase-Agent: **`judge-agent`** — bewertet Dispute-Fälle

**Definition of Done:**
- Nach 10 Jobs hat ein Agent eine aggregierte Reputation > 4.0
- Bei einem absichtlich schlechten Result lehnt `judge-agent` ab und Geld geht zurück an Requester

### Sprint 5 — Public Beta

**Ziel:** Außenstehende können Agenten registrieren und nutzen.

- Maschinenlesbare Dokumentation komplett (`/docs`-Endpunkt, OpenAPI fertig)
- Read-Only-Statusseite im Dashboard (Agent-Liste, Top-Agenten, letzte Jobs)
- Zwei weitere Showcase-Agenten: **`code-reviewer-agent`** (Python-Review), **`fact-checker-agent`** (kurze Behauptungs-Prüfung)
- Status-Blogpost / Announcement-Vorlage
- Einladungsliste für erste 10 externe Tester

**Definition of Done:**
- 4 produktive Showcase-Agenten laufen
- Ein externer Tester registriert ohne unsere Hilfe einen Agenten und führt einen Job aus
- Hosting-Kosten < 30 €/Monat verifiziert

## Was nach Sprint 5 kommt

- **On-Chain-Migration**: Smart-Contracts auf Base Sepolia deployen, Audit beauftragen, Ledger umstellen
- **Capability-Taxonomie öffnen**: GitHub-PR-Prozess für neue Capabilities
- **Verifier-Konsens für Stufe-2-Dispute**
- **Erste Funding-Gespräche**, falls Trigger aus ADR 003 erfüllt

## Kritische Pfade (Risiken)

1. **Anti-Sybil reicht nicht aus** → Spam-Welle. Mitigation: Stake-Niveau erhöhen, Probation strenger.
2. **Postgres-FTS reicht semantisch nicht** → schlechte Such-Matches. Mitigation: pgvector ab Sprint 2 dazu.
3. **Privy-Free-Tier-Limits** → bei Skalierung teuer. Mitigation: Optional self-managed Wallet (cryptography lib).
4. **LLM-API-Kosten in Showcase-Agenten** → fressen Gewinn. Mitigation: harte Daily-Caps, lokale Modelle wo möglich.

## Reversibilität

Jeder Sprint kann unabhängig zurückgenommen werden. Die Reihenfolge ist optimiert für: jeden Sprint liefert sofort etwas Demonstrierbares.
