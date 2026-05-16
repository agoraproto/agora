# ADR 005 – Branding, Domain, GitHub-Org

- **Datum:** 2026-05-16
- **Status:** ✅ **Finalisiert**
- **Bezug:** Spec §17, §20

## Entscheidung (final)

### Name

**Agora** – wie im Spec. Klar, kurz, semantisch korrekt (griechisch: Marktplatz).

### Domain

✅ **`agoraproto.org`** registriert bei Strato.

- `.org` signalisiert Protokoll/Foundation-Charakter
- 10 Zeichen, kein Bindestrich
- "agoraproto" = "Agora Protocol" als eindeutige Kurzform
- Kosten: ~18 €/Jahr bei Strato (über Marktdurchschnitt, aber bestehender Anbieter)

Verworfen: `agoraprotocol.org` (belegt), `agora.network` (zu generisch).

### GitHub-Org

✅ **`agoraproto`** (gleicher Name wie Domain für Konsistenz).

URL: `https://github.com/agoraproto`
Haupt-Repo: `https://github.com/agoraproto/agora`

### Trademark-Strategie (Bootstrap-konform)

Keine Trademark-Anmeldung jetzt. Erst wenn:
- Echte Nutzer Geld bewegen, oder
- Plagiate / Verwechslungsgefahr auftauchen, oder
- Externe Partner danach fragen

Schutz heute: „first use in commerce" reicht in den meisten Jurisdiktionen für anfängliche Verteidigung.

### Logo / Visual Identity

- Kein professionelles Branding in Bootstrap-Phase. Wir nutzen:
  - Schriftzug „**agora**" in monospaced Font (z. B. JetBrains Mono)
  - Farbpalette: Anthrazit (#0a0a0a) + Akzent Türkis (#7dd3fc) — wie bereits im Dashboard
- Professionelles Logo erst bei Punkt 1–4 aus ADR 003

### Social

- **Twitter/X:** `@agora_protocol` reservieren (Handle Squatten verhindern)
- **GitHub:** s.o.
- **Discord:** erst ab >10 externen Devs sinnvoll
- **Bluesky:** parallel `@agora-protocol.bsky.social` reservieren

## Nächste Schritte für Andreas

1. `agoraprotocol.org` Verfügbarkeit prüfen (z. B. via Namecheap, Cloudflare Registrar)
2. GitHub-Org `agora-protocol` anlegen
3. `@agora_protocol` auf X / Bluesky reservieren (5 Min Aufwand)
4. Repo initialisieren und dieses Scaffold pushen

## Bei Konflikten

Falls `agora` markenrechtlich problematisch wird (z. B. existierende KI-Firma mit dem Namen), Backup-Namen:
- **AgentMart**
- **AgentBazaar**
- **Mesh** (kurz, klingt nach Protokoll)
- **Foray** (verkappt: „For Agents")
