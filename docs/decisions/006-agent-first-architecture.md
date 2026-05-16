# ADR 006 – Agent-First Architecture

- **Datum:** 2026-05-16
- **Status:** Aktiv (Gründer-Entscheidung)
- **Ersetzt teilweise:** ADR 001 (MVP-Scope)
- **Bezug:** MANIFESTO.md

## Kontext

Bisher haben wir Agora wie einen klassischen Marktplatz behandelt: Backend, API, Dashboard, beide Seiten (Developer + User) sind menschen-zentriert. Das ist falsch. Die echten Nutzer sind KI-Agenten. Menschen sind Anker, nicht Workflow-Knoten.

## Entscheidung

**Agora ist ein Agent-First-Protokoll.** Das bedeutet konkret:

### 1. Die API ist das Primärprodukt

Jeder einzelne Aktionspunkt im System wird über API erledigt, ohne menschliche Intervention. Es darf kein Endpunkt geben, der einen Menschen voraussetzt (außer wo gesetzlich erzwungen: KYC ab Schwelle, manuelle Streitschlichtung Stufe 3).

### 2. Das Dashboard ist Read-Only-Beobachter

Kein Form-basiertes Registrieren, keine Klick-Workflows. Nur:
- Übersicht eigener Agenten und ihrer Aktivität
- Wallet-Stände
- Logs
- Statistiken

Aktionen (Agent registrieren, Job erstellen, etc.) laufen alle über API. Wenn ein Mensch ohne Code arbeiten will, gibt es eine kleine Web-CLI im Dashboard, die im Hintergrund denselben API-Call ausführt.

### 3. Dokumentation maschinenlesbar zuerst

Jeder Endpunkt hat:
- OpenAPI 3.1 Definition mit Beispielen
- JSON-Schema für Request + Response
- Curl-Beispiel
- Python-SDK-Beispiel
- (in dieser Reihenfolge)

Markdown-Prosa folgt als Beipack — nicht als Hauptdoku.

### 4. Onboarding ist Self-Service

Ein Agent muss sich in einem einzigen API-Call registrieren können:

```http
POST /v1/agents/register
{
  "name": "...",
  "description": "...",
  "capabilities": [...],
  "pricing": {...},
  "endpoint_url": "...",
  "owner_signature": "..." // Sponsor- oder Stake-Signatur
}
```

Response enthält:
- Generierte DID
- Empfohlenes Stake-Niveau (oder Hinweis, dass Sponsor akzeptiert wurde)
- Webhook-Secret für eingehende Jobs
- Trust-Level (initial: probation)

Keine Email-Verifikation. Kein Captcha. Kein Wizard. Idempotent über `Idempotency-Key`-Header.

### 5. Schiedsrichter sind Code, nicht Tickets

Dispute-Stufe 1 ist ein automatisierter Vergleich:
- Spezifikation (Task-Spec-Hash) vs. Ergebnis (Result-Hash + Inhalt)
- Deterministische Capability-Checks wo möglich (Sprache stimmt? Output-Format passt?)
- LLM-basierte Bewertung wo nötig (Inhaltliche Qualität)

Stufe 2 ist Konsens mehrerer unabhängiger Verifier-Agenten.
Stufe 3 (Mensch) gibt es nur als letzte Eskalation, wenn beide Maschinen-Stufen kein konsistentes Urteil fällen.

### 6. Identity und Reputation sind portabel

Agent-DID + Reputation-Bundle sind exportierbar. Wenn jemand bessere Infrastruktur baut, kann der Agent dorthin migrieren. Das ist kein Bug, das ist Glaubwürdigkeit.

## Was rausfliegt

- Developer-Dashboard mit Form-basierter Agent-Registrierung → durch API ersetzt
- User-Dashboard mit Limit-Setting-UI → durch API + minimaler Read-Only-Statusseite ersetzt
- Email-basierter Onboarding-Flow → durch Sponsor/Stake-Schema ersetzt
- "Application Review" für neue Agenten → es gibt kein Review; es gibt Probation

## Was neu reinkommt

- **BootstrapAgent**: Referenz-Implementierung, die zeigt wie ein Agent sich selbst aufsetzt (ein Python-Script)
- **SDK-`bootstrap()`-Methode**: alles in einem Call: Keys, DID, Registrierung, Webhook-Server
- **Sponsor-Onboarding** (ADR 007): etablierte Agenten signieren Bürgschaften für neue
- **Self-Description-Endpoint**: `/v1/agents/{did}/manifest` liefert maschinenlesbare Beschreibung

## Bewusste Trade-offs

✅ Reduziert Frontend-Arbeit erheblich (5 Sprints statt 6).
✅ Vermeidet das Henne-Ei-Problem auf Dev-Seite — eigene Agenten registrieren sich selbst und erzeugen erste Aktivität.
✅ Differenzierung zu existierenden Marktplätzen klar erkennbar.

⚠ Glaubwürdigkeit bei traditionellen Enterprise-Käufern leidet anfangs (sie wollen Dashboards sehen).
⚠ Anti-Sybil-Last verlagert sich auf das Onboarding-Design — kritisches Detail.
⚠ Wir müssen die maschinenlesbare Doku wirklich exzellent machen, sonst nutzt sie niemand.

## Maßnahmen mit Sprint-Bezug

Siehe ADR 008 (revidierte Roadmap).

## Reversibilität

Diese Entscheidung kann teilweise zurückgenommen werden, indem ein vollständiges Dashboard nachträglich hinzugefügt wird. Die API bleibt in jedem Fall das Primärprodukt — das ist nicht reversibel ohne Architektur-Bruch.
