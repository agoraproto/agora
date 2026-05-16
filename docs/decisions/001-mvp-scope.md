# ADR 001 – MVP-Scope-Zweiteilung

- **Datum:** 2026-05-16
- **Status:** Vorgeschlagen (zur Bestätigung durch Andreas)
- **Bezug:** Spec §12, Review §4.1

## Kontext

Die Spezifikation v1.1 fordert in 90 Tagen einen MVP mit DID + Registry + Smart Contracts (Mainnet/Sepolia) + Reviews + Disputes + 2 SDKs + 2 Dashboards + 5–10 Showcase-Agenten + Vertical-Launch. Realistisch mit 10 Personen ist das nicht.

## Entscheidung

Wir zweiteilen den MVP in α (Tag 1–60) und β (Tag 60–120):

**α-Phase (Tag 1–60): Off-Chain-First**
- Backend-Kern (FastAPI)
- DID-Registry (`did:agora:`-Methode, eigene)
- Capability-Registry inkl. Suche
- Job-Lifecycle als REST + Webhooks
- Off-Chain-Ledger (Postgres) für Zahlungen
- Python-SDK
- Developer-Dashboard (Light)
- Zwei eigene Showcase-Agenten

**β-Phase (Tag 60–120): On-Chain + Polish**
- Smart-Contract auf Base Sepolia (kein Mainnet vor Audit)
- TypeScript-SDK
- User-Dashboard
- Erste externe Beta-Devs
- 3 weitere Showcase-Agenten

**Vertical-Launch (Tag 120+):** Faktenprüfung mit Marketing.

## Konsequenzen

✅ Realistisches Lieferversprechen.
✅ Frühes Off-Chain-Testing zeigt Protokoll-Probleme, bevor Smart Contracts deployed sind.
✅ Audit kann parallel zur β-Phase laufen.
⚠ Externe Erwartungen müssen neu kommuniziert werden.
⚠ Eigene Methode `did:agora:` schafft Lock-in-Risiko – muss in Phase 2 zusätzlich `did:web` unterstützen.
