# Kritisches Review der Agora-Spezifikation v1.1

> Reviewer: Claude (Cowork) · Datum: 2026-05-16
> Bezugsdokument: `agora spezifikation.md` (1.629 Zeilen, Version 1.1)
> Ziel: Lücken, Widersprüche, technische Risiken, unrealistische Annahmen aufzeigen und priorisierte Verbesserungen vorschlagen.

---

## 0. Executive Summary des Reviews

Die Spezifikation ist außergewöhnlich gut strukturiert, technisch fundiert und in vielen Aspekten umsetzungsreif. Sie ist eines der durchdachtesten Greenfield-Specs, die ich gesehen habe.

**Aber:** Es gibt drei Klassen von Problemen, die vor der Implementierung gelöst werden müssen:

1. **Wirtschaftlich-mathematische Inkonsistenzen** in den Unit Economics (Plattformgebühr ≤ Gasgebühr, Burn-Rate zu niedrig, Seed-Größe knapp).
2. **Architektonische Lücken** an Übergängen (CDN für Job-Inhalte, Recovery-Flows, KI-Schiedsrichter-Trustanker, MCP-Erweiterungen).
3. **Regulatorisches Unterschätzen** (EU AI Act, MiCA-Lizenzabhängigkeit, KYC-Schwellenwerte vs. „offen für alle").

**Empfehlung:** Spec auf v1.2 heben, bevor Tag-1-Code geschrieben wird. Dieses Review liefert die priorisierte Liste der Änderungen.

---

## 1. Stärken (was richtig gut ist)

| # | Stärke | Belegstelle |
|---|---|---|
| 1 | Klare 6-Schichten-Architektur, jeweils mit Zweck, Technik, Beispiel | Kap. 6 |
| 2 | Konkretes Datenmodell mit FK-Beziehungen | Kap. 7 |
| 3 | API-Endpunkte spezifisch genug zum Codieren | Kap. 8 |
| 4 | Realistischer MVP-Scope mit klarer Negativliste | Kap. 12 |
| 5 | Explizit benannte offene Entscheidungen | Kap. 17, 21.21 |
| 6 | Sicherheits-Bedrohungsmodell vorhanden | Kap. 11 |
| 7 | DSGVO-Blockchain-Spannungsfeld adressiert | Kap. 21.10 |
| 8 | Protokoll-Versionierung mit Migrationsphasen | Kap. 21.12 |
| 9 | Realistischer Multi-Tier-Dispute-Mechanismus | Kap. 6.7 |
| 10 | Glossar für Cross-Disziplin-Lesbarkeit | Kap. 19 |

---

## 2. Inhaltliche Widersprüche

### 2.1 Gebühren-Widerspruch („offen vs. kostenpflichtig")

- **Kap. 5.3** Grundprinzip 1: *„Niemand wird ausgeschlossen, niemand zahlt für Mitgliedschaft."*
- **Kap. 21.1**: *„5 € einmalig zur Erstellung jedes Agenten (Sybil-Schutz)"* und *„50–500 €/Jahr Premium-Identität"*.

Auch wenn das eine eine Einmalgebühr und das andere Premium ist – formal widerspricht es dem Grundsatz. **Empfehlung:** Prinzip umformulieren in *„Kein Tor für Profitmaximierung, nur Anti-Sybil-Schwellen"* und die 5 € klar als anti-spam-Mechanismus, refundierbar bei nachgewiesener Aktivität (z. B. erste 10 erfolgreiche Jobs).

### 2.2 Unit Economics rechnen sich nicht

- **Kap. 14.3** Durchschnittliche Transaktion: 0,10 €
- **Plattformgebühr:** 0,5 % → 0,0005 € pro Transaktion
- **Gasgebühr (Kap. 21.1):** *„typisch < 0,01 €"* → **20× höher als die eigene Gebühr**

**Konsequenz:** Bei niedrigem Volumen verliert Agora pro Transaktion Geld, sobald Gas vom Anbieter (z. B. via Paymaster oder gesponserte ERC-4337-UserOps) subventioniert wird. Bei 1 Mio. TX/Tag = 500 €/Tag Umsatz ≠ Infrastrukturkosten (mind. 333 €/Tag laut Kap. 21.18, plus Gas-Subventionen, plus Personal).

**Empfehlung:**
- Mindestgebühr pro TX (z. B. 0,002 €), proportional bei größeren Beträgen
- Oder: Plattformgebühr ab 1 % statt 0,5 % im MVP
- Oder: Gas-Pass-Through (Nachfrager zahlt explizit, kein Paymaster für Mikrotransaktionen)
- Annahme „Durchschnittstransaktion 0,10 €" hinterfragen: Bei realer LLM-API-Ökonomie sind 0,30–2,00 € realistischer

### 2.3 MCP als Basis für Marktplatz-Protokoll

- **Kap. 6.4**: *„Basis: Model Context Protocol (MCP) von Anthropic"*
- **Realität:** MCP ist ein Tool-/Context-Protokoll mit Client-Server-Modell – kein Peer-to-Peer-Marktplatz, kein Negotiation-Modell, keine Payment-Primitives, kein Reputation-Layer.

Es ist nicht falsch, MCP-Konzepte (Tool-Manifest, JSON-RPC) zu übernehmen, aber zu sagen *„auf MCP-Basis"* erweckt den falschen Eindruck von Drop-in-Kompatibilität.

**Empfehlung:** Klarstellen, dass Agora MCP-**inspiriert** ist (gleiche Wire-Format-Konventionen für Tools), aber ein eigenständiges Protokoll mit eigener Spezifikation darstellt. Optional: MCP-Bridge bauen, sodass Agora-Service-Agenten via MCP-Server angesprochen werden können.

### 2.4 Doppelte Gebühren-Quote

- **Kap. 5.3 + 6.5:** 0,5–1 %
- **Kap. 21.1:** 0,5–1 % Plattform **plus** 0,1 % Versicherungspool

→ Effektiv 0,6–1,1 %. Sollte konsolidiert dargestellt werden, sonst Misstrauen bei Entwicklern.

### 2.5 KYC schließt aus

- **Kap. 5.3:** *„Niemand wird ausgeschlossen"*
- **Kap. 11.3:** KYC ab 1.000 €/Tag Umsatz für „verifizierte Owner"

Pseudonyme Wal-Agenten sind also ausgeschlossen. Konsistenz fehlt.

### 2.6 Mutual Rating ohne Retaliation-Schutz

- **Kap. 6.6** sagt: *„Mutual Rating; einseitige Bewertungen werden niedriger gewichtet"*
- **Problem:** Wenn beide gleichzeitig bewerten, retaliation-rated der schlechter Bewertete den anderen. Reciprocity ist eines der bekanntesten Reputation-System-Probleme.

**Empfehlung:** Blind-Reviews (beide reichen ein, Veröffentlichung erst nach Frist), oder Reputation-Stake (Bewerter setzt Reputation aufs Spiel bei Ausreißer-Bewertungen), oder asymmetrische Sichtbarkeit.

---

## 3. Architektonische Lücken

### 3.1 Wer hostet die Agora-Registry?

Die Spec nennt die „Agora-Registry" als zentralen Knoten für DID-Veröffentlichung und Capability-Suche, sagt aber nicht:
- Ist sie zentral (Single Point of Failure, Single Point of Trust)?
- Föderiert (mehrere Registries syncen)?
- Vollständig dezentral (IPFS/Ceramic)?

Für „offenes Protokoll" ist Zentralität problematisch – aber Föderation ist komplex.

**Empfehlung:** Phase 1 zentral, Phase 2 multi-registry mit verifiziertem Cross-Sync (ähnlich Mastodon-/ActivityPub-Modell). Klar dokumentieren, dass es einen „Reference Registry" bei Agora gibt.

### 3.2 CDN für Job-Inhalte ist nicht spezifiziert

- **Kap. 6.4 Beispiel-Nachricht:** `"input": "https://agora.cdn/docs/encrypted_doc_x7f.bin"`
- **Offen:** Wer hostet `agora.cdn`? Wer trägt Kosten? Wie lange? Wer hat Zugriff? Wie wird die Verschlüsselung gemacht? Was, wenn der Service-Agent das File nicht herunterladen kann?

**Empfehlung:** Eigene Sub-Spezifikation **AGS-S3** (Agora Storage Spec) mit:
- E2E-Verschlüsselung mit Empfänger-Public-Key (X25519)
- Content-addressed storage (Hash-basiert)
- Aufbewahrung 30 Tage Default
- Push-Option (Inline-Payloads bis 64 KB)
- Pull-Option (Presigned-URLs mit kurzer TTL)

### 3.3 Identity Recovery fehlt komplett

Was, wenn ein User/Developer den DID-Private-Key verliert?
- Sein User-Agent kann nicht mehr signieren → keine Jobs mehr
- Sein Wallet ist potenziell verloren → Mittel im Escrow gefangen
- Reputation ist an die DID gebunden → nicht migrierbar

**Empfehlung:**
- **Social Recovery** (Argent-/Safe-Style): N-of-M Guardians können neuen Key autorisieren
- **Custodial Fallback** (Privy/Magic): Email-basierte Recovery
- **Stake-basierte Recovery-Periode**: 7 Tage Frist, in der alte Schlüssel widersprechen können

### 3.4 Endpoint-Verification

- **Kap. 6.2:** *„serviceEndpoint": "https://agent.example.com/api/v1"*
- **Offen:** Wer verifiziert, dass dieser Endpoint zum Owner der DID gehört? Aktuell kann ich `did:web:agora.com` registrieren und den Endpoint auf meine kontrollierte URL zeigen lassen.

**Empfehlung:** Domain-Verification via DNS-TXT-Record oder `.well-known/agora-agent.json` mit Signatur. Beim ersten POST `/v1/agents/register` Verifikation triggern.

### 3.5 Recursive Composition nicht spezifiziert

Die Spec deutet an, dass Service-Agenten andere Service-Agenten beauftragen können (Kap. 4.2 *„Andere Spezialisten-Agenten: Agenten, die wiederum andere Agenten brauchen (rekursiv)"*), aber:
- Wer haftet bei Fehlern in der Kette?
- Wer bekommt die Reputation für gute Arbeit?
- Wie wird das Budget weitergereicht?
- Wie tief darf die Rekursion gehen (DoS-Schutz)?

**Empfehlung:** Explizite Sub-Job-Spec mit Parent-Job-ID, Budget-Cap, Max-Depth (z. B. 3), Haftungs-Kettenregel.

### 3.6 Smart-Contract-Spec ist Pseudocode-only

Die Solidity-Skizze in **Kap. 6.5** lässt offen:
- Wer ist Arbiter? Wer kann `dispute()` aufrufen?
- Was passiert bei Deadline-Überschreitung ohne `approveAndPay` oder `dispute`?
- Wer trägt Gas für `refund()`?
- Upgradeability? Proxy-Pattern?

**Empfehlung:** Vor Phase-1-Implementierung: vollständiger Contract-Stub plus eine erste Foundry-Test-Suite. Audit-Punkte vorab definieren.

### 3.7 Trust-Anker für KI-Schiedsrichter

- **Kap. 6.7 Stufe 1:** *„Spezialisierte Schiedsrichter-Agenten prüfen das Ergebnis"*
- **Logisch:** Diese sind selbst Agenten auf Agora. Wer auditiert sie? Wer verhindert Bias? Was, wenn Schiedsrichter und Service-Agent denselben Owner haben?

**Empfehlung:**
- Schiedsrichter-Agenten müssen:
  - Higher Stake hinterlegen (z. B. 1.000 €)
  - Open-Source-Modelle nutzen (oder mind. open-weights)
  - Owner-Disjunktheit von zu prüfenden Agenten (FK-Constraint)
  - Random-Round-Robin-Pool (keine Auswahl durch Partei)
  - 3-Schiedsrichter-Konsens (nicht 1)

### 3.8 State Channels nicht spezifiziert

**Kap. 6.5** nennt State Channels für Mikrotransaktionen, ohne Spec:
- Bilateral oder N-Party?
- Wer hostet Watchtower?
- Channel-Lifetime, Settlement-Trigger?
- Capital-Lock-Up pro Channel?

State Channels sind eine eigene Spec-Welt. **Empfehlung:** Im MVP **nicht** verwenden, stattdessen Layer-2 (Base) mit Batch-Settlement. State Channels in Phase 3+.

### 3.9 Webhook-Reach für Enterprise-Agenten

Service-Agent-Webhooks müssen öffentlich erreichbar sein. Enterprise-Setups (hinter Firewall) können das nicht. **Kap. 21.14** spricht Webhook-Signaturen an, nicht Reverse-Tunneling.

**Empfehlung:** Long-Polling-Fallback oder WebSocket-Outbound-Connection für Service-Agenten ohne Public Endpoint.

### 3.10 SDK-Sharing über IDL

4 SDK-Sprachen (Python, TS, Go, Rust) ohne gemeinsame **Schema-Source-of-Truth** = Drift garantiert.

**Empfehlung:** Single Source = OpenAPI 3.1 + JSON-Schema für alle Datenstrukturen. SDKs **generiert** aus Spec (z. B. via `openapi-generator` oder `oapi-codegen`). Erweitert um handgeschriebene High-Level-Helper.

---

## 4. Unrealistische Annahmen

### 4.1 90-Tage-MVP

**Geforderter Scope** (Kap. 12.1):
- DID-Registry mit `did:web`
- Capability-Registry mit Volltextsuche
- Synchrone API für Agent-zu-Agent
- Smart-Contract Escrow auf Base mainnet (oder Sepolia)
- 5-Sterne-Reputation
- Manueller Dispute
- Python-SDK
- TypeScript-SDK
- Developer-Dashboard (Web)
- User-Dashboard (Web)
- 5–10 eigene Showcase-Agenten
- Vertical „KI-Faktenprüfung" launch-ready
- 100 Agents + 1.000 TX gewonnen

**Realistisch in 90 Tagen mit 10 Personen?** Eher 50–60 % davon. Wahrscheinlicher 4–6 Monate.

**Empfehlung:** MVP-Scope zweiteilen:
- **MVP α (Tag 1–60):** Backend-Kern + ein SDK + Dev-Dashboard. Keine Smart Contracts, Off-chain-Ledger.
- **MVP β (Tag 60–120):** Smart Contracts auf Sepolia, zweites SDK, User-Dashboard, 3 Showcase-Agenten.
- **Vertical-Launch (Tag 120+):** Faktenprüfung mit Marketing.

### 4.2 Burn-Rate-Realismus

**Kap. 21.18:** 100.000 €/Monat Personal für 10 Personen = Ø 10.000 €/Monat brutto pro Person.

- Senior Solidity Engineer in EU: **180.000–250.000 €/Jahr** all-in (Markt 2025/26)
- Senior Backend Engineer in EU: 110.000–160.000 €/Jahr
- Security Engineer: 140.000–200.000 €/Jahr

Realistische Kosten 10 Personen, gemischt: **140.000–180.000 €/Monat** all-in. → **Jahres-Burn 4,5–5,5 Mio. €**, nicht 3,26 Mio. €.

**Empfehlung:** Seed-Größe auf 5–6 Mio. € erhöhen oder Team kleiner halten (6 Personen Jahr 1).

### 4.3 Onboarding < 10 Minuten

Ein Service-Agent braucht für Onboarding:
1. Schlüsselpaar generieren
2. DID-Dokument bauen
3. `did:web` DNS-Eintrag oder Endpoint mit `.well-known/`-Datei
4. Webhook-Endpoint öffentlich machen
5. Capabilities deklarieren (JSON-LD)
6. Pricing definieren
7. Smart-Wallet erstellen
8. Stake einzahlen
9. Endpoint-Verifikation

Mit hervorragendem Onboarding-Wizard: 10 min plausibel. **Aber:** `did:web` braucht DNS-Kontrolle – das ist für viele Hobby-Devs eine Stunde Frust. **Empfehlung:** Für MVP `did:agora:` (selbst-gehosted) als Default, `did:web` als Power-User-Option.

### 4.4 100 externe Entwickler-Agenten in 12 Monaten

Ohne Token-Incentive und ohne Big-Tech-Partner sind 100 externe High-Quality-Agenten in 12 Monaten ambitioniert. Reale Vergleichswerte:
- HuggingFace-Hub: Brauchte 18 Monate für ersten 1.000 Modelle
- LangChain-Hub: Anfangs viel Spam, wenige produktionsreife Custom-Components

**Empfehlung:** Ziel auf 30 produktionsreife externe Agenten relaxen. 1-Mio-€-Grants müssen klare Acceptance-Kriterien haben (z. B. ≥100 erfolgreiche Jobs, Reputation ≥4.0 nach 60 Tagen) sonst Spam-Anreiz.

### 4.5 Durchschnittliche TX-Latenz < 1 s

Klar verfehlt für jeden Service-Agent, der einen LLM-Call macht. Claude/GPT-4-Class-LLM-Latency = 2–10 s pro Antwort. **Empfehlung:** SLA differenzieren:
- Protokoll-Latenz (Offer/Accept-Handshake): < 500 ms
- Job-Latenz: vom Agent deklariert, je nach Capability (z. B. 30 s für Übersetzungen, 5 min für Recherche)

### 4.6 Mainnet-Launch in MVP

Mainnet-Smart-Contracts ohne Audit sind grob fahrlässig. Audits dauern 4–8 Wochen (Trail of Bits, OpenZeppelin, Certora). Das ist **mit** dem 90-Tage-MVP unvereinbar.

**Empfehlung:** Sepolia in MVP, Mainnet erst nach Audit (Monat 5–6).

---

## 5. Regulatorische Risiken (vom Dokument unterschätzt)

### 5.1 EU AI Act

Agora ist ein Marktplatz für KI-Systeme. Je nach Verwendung der Agenten kann Agora als **„General Purpose AI System Provider"** klassifiziert werden – mit erheblichen Transparenz- und Reporting-Pflichten.

Insbesondere wenn Agenten in **High-Risk-Anwendungen** (Medizin, Recht, HR, Kreditscoring) eingesetzt werden, gelten Annex III-Pflichten **auch für Marktplatz-Betreiber**, die solche Agenten ohne Disclaimer listen.

**Empfehlung:** Capability-Klassifizierung mit Risk-Level (low/limited/high) + automatische Compliance-Checks vor Listing.

### 5.2 MiCA & Stablecoin-Abhängigkeit

USDC und EURC sind reguliert via **MiCA seit Juni 2024** (Circle hat EU-EMI-Lizenz). Aber:
- Wenn Circle die Lizenz verliert/ändert: ganze EU-Operation steht.
- DAI ist **nicht** MiCA-konform → kann nicht in EU eingesetzt werden.
- PYUSD: ungeklärter Status in EU.

**Empfehlung:** Multi-Stablecoin von Anfang an, USDT meiden (kein MiCA), Circle als Hauptlieferant absichern.

### 5.3 KYC-Schwellen und AML

1.000 €/Tag (Kap. 11.3) als KYC-Trigger ist sehr hoch im Vergleich zu **AMLD6** Best Practice (200 €/TX bei Krypto). Bei AML-Inspektion ist 1.000 €/Tag schwer zu verteidigen.

**Empfehlung:**
- KYC ab 100 €/TX oder 500 €/Tag
- Sanctions-Screening bei jeder TX (Chainalysis, TRM Labs)
- Reporting bei verdächtigen Mustern

### 5.4 DSGVO-Tombstone-Status nicht ausreichend

**Kap. 21.10** schlägt „Tombstone-DID" vor (existiert formal, aber leer). DSGVO Art. 17 verlangt Löschung. Tombstone ist Pseudonymisierung – DSGVO-Behörden haben das in mehreren Fällen abgelehnt (z. B. CNIL-Entscheidung 2024 gegen Discord).

**Empfehlung:** Pseudonyme Daten als Default + echte Löschung **inklusive** Off-Chain-Reviews und Job-Logs bei Löschungsantrag. On-Chain bleiben nur Hashes (anonymisiert per Definition, kein Personenbezug).

---

## 6. Sicherheits-Lücken

### 6.1 Anti-Sybil-Mechanismus zu schwach

5 € Einmalgebühr stoppt Hobby-Spammer, nicht professionelle Reputation-Farmer. Bei 100 €/Tag Reputation-as-a-Service ist eine 5-€-Investition irrelevant.

**Empfehlung:** Reputation-Bootstrapping über:
- Mindest-Aktivität (10 erfolgreiche Jobs als „Service") bevor Reviews gewichtet zählen
- Web-of-Trust-Faktor: Reviews von hoch-trusted Agenten zählen mehr
- Probation-Period: Neue Agenten haben Reputation-Cap (max 4.0) für 90 Tage

### 6.2 Endpoint-Spoofing

Wie schon in 3.4 erwähnt – Service-Agent kann fremde Endpoints angeben. Plus: Endpoints können nach Registrierung wechseln – ohne Re-Verification.

**Empfehlung:** Endpoint-Updates triggern Re-Verification + Notification an Reviewer.

### 6.3 Prompt-Injection-Strategie unvollständig

**Kap. 21.13** ist gut, aber:
- „Input-Sanitization auf Protokoll-Ebene" mit XML-Tags wurde bereits 2024 in Sicherheitsforschungen umgangen
- ML-basierte Injection-Scanner haben False-Negative-Raten von 10–30 %

**Empfehlung:** Defense-in-Depth zusätzlich:
- Capability-Scoped Agent-Permissions (Service-Agent kann nicht zufällig Payments triggern)
- Tool-Restrictions auf System-Level (Agent darf nur deklarierte Capabilities, nichts anderes)
- Detection im Output (Agent gibt komische Antworten = Flag)

### 6.4 Smart-Contract: Front-Running von Disputes

Wenn `dispute()` öffentlich auf-on-chain triggerbar ist, kann ein Angreifer die Mempool beobachten und schneller eine Dispute eröffnen, um Escrow zu blockieren.

**Empfehlung:** Commit-Reveal-Pattern für Dispute oder Private-Mempool-Submission (Flashbots-Style).

### 6.5 Reputation-Algorithmus ist manipulierbar

**Kap. 6.6** Python-Beispiel ist primitiv: gewichtete Mittel über Time-Decay und Reviewer-Trust. Angreifer kann:
- Viele Reviewer-Identitäten mit hohem Trust hochzüchten (Sybil)
- Reviewer-Trust ist zirkulär definiert (nicht gezeigt: was macht einen Reviewer „trusted"?)

**Empfehlung:** Reputation als **EigenTrust-Variante** modellieren (PageRank-Style mit Personalisierung), nicht als Mittel über Reviews.

---

## 7. Fehlende Spezifikationen (Must-Have vor Code)

| # | Fehlend | Vorgeschlagene Sub-Spec |
|---|---|---|
| 1 | Storage für Job-Inhalte | AGS-S3 (Storage Sub-Spec) |
| 2 | Identity Recovery | AGS-R1 (Recovery Sub-Spec) |
| 3 | Endpoint-Verifikation | AGS-V1 (Verification Sub-Spec) |
| 4 | Smart-Contract-Vollspec | AGS-SC1 (Solidity-Spec mit States, Events, Errors) |
| 5 | Sub-Job / Recursive Composition | AGS-SUB1 |
| 6 | OpenAPI 3.1 Vollspec | `openapi/agora-v1.yaml` |
| 7 | JSON-Schema für alle Datenstrukturen | `schemas/*.json` |
| 8 | Webhook-Retry-Statemachine | AGS-W1 |
| 9 | Rate-Limiting-Policy | AGS-RL1 |
| 10 | Schiedsrichter-Agenten-Verfassung | AGS-J1 (Judges Sub-Spec) |

---

## 8. Klärungspunkte vor Implementierung (kondensiert aus Kap. 17 & 21.21 + neu)

| # | Frage | Vorgeschlagene Antwort |
|---|---|---|
| 1 | Custody-Modell | **Privy** (UX, Recovery, DSGVO-kompatibel, Smart Accounts native) |
| 2 | MVP-Chain | **Base Sepolia** für MVP, Mainnet nach Audit |
| 3 | Cloud-Region Phase 1 | **AWS eu-central-1 (Frankfurt)** für EU-Compliance |
| 4 | Auth-Provider Dashboard | **Privy** (gleicher Provider, weniger Surface) |
| 5 | Smart-Contract-Audit | **OpenZeppelin** + Code4rena Public Audit |
| 6 | Domain | `agora.dev`, `getagora.ai`, `agoraproto.org` prüfen |
| 7 | GitHub-Org | `agoraproto` oder `agoraproto` |
| 8 | Vertical Phase 1 | **Faktenprüfung** wie spezifiziert |
| 9 | Showcase-Agenten | Faktenprüfer, DE/EN-Übersetzer, Code-Reviewer, Mathe-Verifier, Recherche-Agent |
| 10 | Lizenz Protokoll | **Apache 2.0** wie empfohlen |
| 11 | DID-Methode MVP | **`did:agora:`** (eigene Methode, einfach) **statt** `did:web` |
| 12 | Default-Stablecoin Test | **Mock-USDC** auf Sepolia, später echtes USDC |
| 13 | Storage-Backend | **AWS S3 + KMS** mit E2E-Encryption-Layer |

---

## 9. Priorisierte Action-Items

### Vor Code (Spec v1.2 Update)

1. ✱ Unit Economics neu rechnen (Mindestgebühr, Annahmen)
2. ✱ Anti-Sybil härten (Probation, Web-of-Trust)
3. ✱ Identity-Recovery-Strategie wählen
4. ✱ Storage-Sub-Spec (AGS-S3) entwerfen
5. ✱ Smart-Contract-Vollspec inkl. States & Events
6. ✱ EU AI Act + MiCA Compliance-Plan (mit Anwalt)
7. ✱ OpenAPI 3.1 Spec als Single-Source-of-Truth
8. ✱ KYC-Schwelle revidieren (200 €/TX statt 1.000 €/Tag)
9. ✱ MVP-Scope realistisch zweiteilen (α + β)
10. ✱ Burn-Rate / Seed-Größe korrigieren

### Im Code-Aufbau (Phase 1)

11. Monorepo-Struktur (Turborepo + pnpm)
12. Docker-Compose lokal (PG, Redis, Qdrant, Typesense, Anvil)
13. FastAPI-Skeleton mit Auth-Layer (Privy)
14. SQLAlchemy + Alembic mit allen Entitäten
15. OpenAPI-First Workflow + Codegen
16. Foundry-Setup mit Mock-Escrow auf Anvil
17. Erste E2E-Demo: 2 Test-Agenten, 1 Job, off-chain Settlement

### Nach MVP α

18. Smart-Contract-Audit beauftragen
19. KI-Schiedsrichter-Verfassung schreiben
20. Mainnet-Migration

---

## 10. Schlussbemerkung

Die Agora-Spec ist **näher an einem buildbaren Produkt als 95 % aller Specs**, die ich gesehen habe. Die obigen Punkte sind kein „Verwerfen", sondern „Schärfen". Wenn Punkte 1–10 in einer v1.2 nachgezogen werden, ist Agora bereit für einen seriösen Build-Start.

**Mein Vertrauenslevel in das Konzept:** hoch.
**Mein Vertrauenslevel in die 90-Tage-Timeline:** mittel-niedrig ohne Scope-Adjustment.
**Mein Vertrauenslevel in die Wirtschaftlichkeit (Phase 1–2):** niedrig ohne Unit-Economics-Reform.
**Mein Vertrauenslevel in den Markt-Fit (Phase 3+):** sehr hoch.

— Ende des Reviews —
