# ADR 003 – Bootstrap-Strategie (kein Seed-Kapital initial)

- **Datum:** 2026-05-16
- **Status:** Aktiv (Andreas-Entscheidung)
- **Bezug:** Review §4.2, ADR 001

## Kontext

Statt einer 3,5–6 Mio. € Seed-Runde wird Agora **bootstrap-finanziert** gebaut: erst entwickeln, validieren, laufen lassen — dann reden wir über Geld, wenn wir merken, wir brauchen Verstärkung. Das ist nicht „weniger MVP", sondern **anderes MVP**: Statt Plattform-Ambition zuerst die **kleinste funktionierende Schleife** bauen.

## Konsequenzen für Scope und Tempo

### Was bleibt (unverzichtbarer Kern)

1. **Backend-API** (FastAPI) – läuft auf einem einzigen kleinen Server (5–10 €/Monat)
2. **DID-Registry** mit eigener Methode `did:agora:` (kein DNS-Setup nötig)
3. **Capability-Suche** – startet mit reinem Postgres-Volltext, kein Typesense/Qdrant nötig (zumindest am Anfang)
4. **Job-Lifecycle** – synchron, kein Async/Webhooks im allerersten Build
5. **Off-Chain-Ledger** (Postgres) für Zahlungen — kein Smart Contract, kein Gas
6. **Ein einziges SDK** (Python) — TypeScript folgt erst, wenn echte Nutzer fragen
7. **Ein Dashboard** (Next.js, minimal) — eigentlich nur für eigene Showcase-Agenten
8. **Zwei eigene Showcase-Agenten** — Faktenprüfer + Übersetzer

### Was rausfliegt (vorerst)

- ❌ Mainnet-Smart-Contracts → Off-Chain-Ledger zunächst
- ❌ Audit-Pflicht → kein Audit nötig, solange kein echtes Geld onchain läuft
- ❌ Typesense + Qdrant → ersetzt durch Postgres FTS + pgvector-Extension
- ❌ Anvil/Foundry im täglichen Dev-Loop → Contracts existieren als Spec/Stub für später
- ❌ Multi-Region, k8s, Grafana → ein Server, simple Logs
- ❌ Bug-Bounty-Programm → erst wenn echtes Geld fließt
- ❌ Dev-Relations-Team → Andreas + Claude
- ❌ Grants-Programm → erst nach erster Validierung
- ❌ 5 SDK-Sprachen → eines reicht
- ❌ Versicherungspool → kein echter Schaden möglich ohne Onchain-Payments
- ❌ KI-Schiedsrichter-Agenten → Disputes manuell via Admin-Endpoint

### Realistische Zeitlinie (Solo / Andreas + Claude)

| Sprint | Dauer | Lieferung |
|---|---|---|
| **Sprint 1** | ~2 Wochen | DID-Generierung + Agent-Register-Endpunkt + Postgres-Migrationen |
| **Sprint 2** | ~2 Wochen | Capability-Suche (Postgres FTS) + erste Showcase-Agent-Registrierung |
| **Sprint 3** | ~2 Wochen | Job-Lifecycle (offer/accept/result/approve) synchron |
| **Sprint 4** | ~2 Wochen | Off-Chain-Ledger + Reviews + Reputation-Aggregate |
| **Sprint 5** | ~2 Wochen | Python-SDK polieren + 2 Showcase-Agenten (Faktenprüfer, Übersetzer) |
| **Sprint 6** | ~2 Wochen | Dashboard (minimal), erste echte Test-Flows, Doku |

→ **~3 Monate** kalendarisch bei realistischem Teilzeit-Tempo. Kein 10-Personen-Team, kein 90-Tage-Druck.

## Infrastruktur-Kostenplan (max. ~20 €/Monat)

| Komponente | Kosten/Monat |
|---|---|
| VPS (Hetzner CX22, 4 GB RAM, 2 vCPU) | 4,51 € |
| Domain (.org) | ~1 € (10–15 €/Jahr umgerechnet) |
| Postgres (auf VPS, kein Managed Service) | inklusive |
| Backups (Hetzner Snapshots) | ~1 € |
| Cloudflare (Free Tier) | 0 € |
| Privy (Free Tier für < 1.000 MAU) | 0 € |
| GitHub Actions (Free Tier) | 0 € |
| Sentry (Free Tier) | 0 € |
| LLM-API-Calls für Showcase-Agenten | variabel, Cap auf 10–30 € |
| **Geschätzt total** | **~15–30 €/Monat** |

## Grenze: Wann brauchen wir Kapital / Hilfe?

Wir suchen Geld/Verstärkung **erst**, wenn eines davon eintritt:

1. **Nachfrage-Signal** – mehr als 5 ernsthafte externe Devs fragen aktiv nach Onboarding
2. **Skalierungs-Schmerz** – >1.000 echte Jobs/Tag und der VPS keucht
3. **Onchain-Schritt** – wir wollen echtes Geld fließen lassen → Audit nötig → 30–80 k €
4. **Compliance-Schwelle** – wir erreichen einen Punkt, an dem MiCA/AI-Act-Beratung unverzichtbar wird

Bis dahin: **Cash-flow-positiv von Tag 1**, weil keine Burn-Rate über 30 €/Monat.

## Trade-offs

✅ **Wir lernen schneller**, ohne externe Erwartungen.
✅ **Volle Eigentumsrechte**, keine Verwässerung.
✅ **Echte Marktvalidierung** zwingt uns, fokussiert zu bleiben.
✅ **Niedriges Risiko** – wenn es nicht klappt, haben wir nichts verloren außer Zeit.

⚠ **Langsam** im Vergleich zu kapitalisierten Wettbewerbern.
⚠ **Glaubwürdigkeit** vor Enterprise-Kunden braucht Zeit (kein „Series A funded"-Stempel).
⚠ **Bandbreite** – Andreas ist nicht 24/7 verfügbar; Tempo ist „so weit wir kommen".

## Strategie-Schwenk wenn nötig

Sobald die Nachfrage-Signale Punkt 1–4 eintreten, kann jederzeit auf den Original-Plan (Spec §13–14) gewechselt werden. Dieses ADR sperrt nichts dauerhaft, es **verschiebt nur den Start der teuren Phase**.
