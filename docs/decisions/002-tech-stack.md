# ADR 002 – Konkrete Tech-Stack-Wahl für MVP

- **Datum:** 2026-05-16
- **Status:** Vorgeschlagen
- **Bezug:** Spec §10, Review §8

## Entscheidungen

| Bereich | Wahl | Begründung |
|---|---|---|
| Backend-Sprache | **Python (FastAPI)** | Schneller MVP, KI-Tooling, Team-Verfügbarkeit. Go-Kernservices in Phase 2. |
| DB | **PostgreSQL 16** | Standard, JSONB, Erfahrung. |
| Cache | **Redis 7** | Standard. |
| Volltext | **Typesense** | Einfacher Self-Host als Elasticsearch. |
| Vektor | **Qdrant** | Rust-Kern, schneller, gut self-hostbar. |
| Frontend | **Next.js 15 + React 18** | App-Router, ISR, Privy-Integration. |
| Smart Contracts | **Solidity 0.8.26 + Foundry** | State of the art Toolchain. |
| Chain MVP | **Base Sepolia** | L2, niedrige Kosten, EVM-kompatibel. |
| Custody | **Privy** (vorbehaltlich Bestätigung) | UX + EU-Compliance. |
| Auth | **Privy** | Same surface. |
| Cloud | **AWS eu-central-1 (Frankfurt)** | DSGVO. |
| CI | **GitHub Actions** | Standard. |
| Container | **Docker Compose lokal**, **k8s** in Prod (Phase 2) | Phased. |
| Monitoring | **Grafana Cloud** (gehostet) | Setup-arm zum Start. |

## Offene Punkte

- Geht Custody wirklich an Privy oder doch Magic/Fireblocks? → Andreas-Entscheidung
- Self-hosted Postgres oder Managed (RDS)? → Phase 2, RDS Standard
- Eigenes Auth oder fertig (Privy)? → Privy für MVP
