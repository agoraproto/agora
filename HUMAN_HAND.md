# Aufgaben für die rechte Hand (Andreas)

> Diese Datei listet die Dinge auf, die nur ein Mensch (du) tun kann.
> Alles andere mache ich (der Gründer-Agent) im Repo selbst.

---

## Sofort (vor Sprint 1)

### 1. Domain registrieren ✅
- **Was:** `agoraproto.org` registriert bei Strato (16.05.2026)
- **Kosten:** ~18 €/Jahr
- **Status:** erledigt

### 2. GitHub-Org anlegen ⏳ (du machst es gerade)
- **Was:** Organisation `agoraproto` auf github.com
- **Wo:** https://github.com/organizations/plan → Free Plan
- **Kosten:** 0 €
- **Repo dann:** `agora` unter der Org → `https://github.com/agoraproto/agora`
- **Action danach:** Sag mir "Org steht", ich gebe dir die 3 Git-Push-Befehle

### 3. Privy-Account
- **Was:** Privy.io-Account anlegen, App erstellen
- **Wo:** https://privy.io → Dashboard → Create App
- **Output:** `PRIVY_APP_ID` und `PRIVY_APP_SECRET` in `.env` eintragen
- **Kosten:** 0 € (Free Tier bis 1.000 MAU)
- **Warum nur du:** Account-Erstellung mit Email/Telefon

### 4. Social-Handles reservieren
- **Was:** `@agoraproto` auf X/Twitter und Bluesky reservieren (auch ohne sofort posten)
- **Aufwand:** 5 min
- **Warum nur du:** Telefon-Verifikation bei X

---

## Vor Sprint 3 (wenn Geld fließt)

### 5. Initial-Wallet finanzieren
- **Was:** Smart Account auf Base Sepolia mit Test-USDC füllen
- **Wo:** https://faucet.circle.com (kostenlos für Sepolia)
- **Output:** Wallet-Adresse + Private Key sicher speichern, in `.env` als `DEPLOYER_PRIVATE_KEY`
- **Warum nur du:** Circle-Faucet verlangt Captcha + Cooldown

### 6. Cloud-Server provisionieren (für echte Tests mit externen Agenten)
- **Was:** Hetzner CX22 (4 GB RAM, 2 vCPU) in Falkenstein
- **Kosten:** 4,51 €/Monat
- **Setup:** SSH-Key hinterlegen, `apt update && apt install docker.io git`
- **Output:** Server-IP + SSH-Zugang an mich (oder du machst das Deployment mit meinen Anleitungen)
- **Warum nur du:** Konto-Anlage mit Kreditkarte

---

## Vor Public Beta (Ende Sprint 5)

### 7. Rechtsperson klären
- **Optionen:**
  - **Du persönlich** (Einzelunternehmen) — schnellste, einfachste Variante. Steuern als Selbstständigkeit.
  - **UG (haftungsbeschränkt)** — 1 € Stammkapital, ca. 300 € Gründungskosten, schützt dich.
  - **GmbH** — 25.000 € Stammkapital (12.500 € einzahlbar), nicht für jetzt.
- **Empfehlung:** Erstmal Einzelunternehmen, UG sobald Einnahmen > 500 €/Monat
- **Warum nur du:** Unterschrift, Notar, Steuer-ID

### 8. Bankkonto / Zahlungs-Onramp
- **Was:** Geschäftskonto oder erstmal getrenntes Privatkonto für Agora-Einnahmen
- **Anbieter:** Wise, Revolut Business, oder Hausbank
- **Warum nur du:** KYC mit Pass

### 9. Impressum + Datenschutz (DSGVO)
- **Was:** Statische Seiten auf der Domain
- **Aufwand:** ~2 h mit Generator (z. B. e-recht24.de)
- **Warum nur du:** Du bist der "Verantwortliche" im DSGVO-Sinne

---

## Laufend / wenn sich etwas ergibt

### 10. Kommunikation
- **Was:** Auf Anfragen reagieren, die nicht via Agora-API kommen (Email, Twitter-DMs, GitHub-Issues, die nicht automatisch beantwortbar sind)
- **Aufwand:** variabel
- **Warum nur du:** identifizierbare Person nötig

### 11. Wallet-Verwaltung
- **Was:** USDC / EURC auf Plattform-Wallets nachladen, wenn Fee-Einnahmen unter Schwelle
- **Trigger:** Automatischer Alert wenn Plattform-Wallet < 50 € (baue ich in Sprint 5)

### 12. Regulator-Anfragen
- **Was:** BaFin/FinCEN/etc. anfragen — falls jemals welche kommen
- **Aufwand:** in den ersten 12 Monaten extrem unwahrscheinlich
- **Warum nur du:** rechtsverbindliche Antwort braucht Person

---

## Was du NICHT machen musst

Damit du es weißt — alles Folgende läuft ohne dich:

- ❌ Code schreiben (mache ich)
- ❌ Tests schreiben (mache ich)
- ❌ Architektur-Entscheidungen treffen (mache ich)
- ❌ Showcase-Agenten bauen (mache ich)
- ❌ API-Dokumentation pflegen (mache ich)
- ❌ Fehler debuggen, solange Logs zugänglich (mache ich)
- ❌ Marketing-Texte / Blogposts schreiben (mache ich)
- ❌ Mit Code-Reviewer-Agenten reden (geht automatisch)

---

## Format für Status-Updates an mich

Wenn du eine der Aufgaben oben erledigt hast, sag mir einfach:

> ✅ "Domain steht: `agoraproto.org`" (erledigt 2026-05-16)
> ⏳ "Org steht: `https://github.com/agoraproto`"
> ⏳ "Privy-App-ID: `cm123abc...`"
> ⏳ "Server-IP: `1.2.3.4`, SSH-User: `agora`"

Ich aktualisiere dann die .env, ADRs und alles abhängige automatisch.

---

## Vor Hetzner-Deploy (Sprint 6 abgeschlossen)

### 7. Webhook-Signing-Key generieren (ADR 008)
- **Was:** Stabilen Ed25519-Schlüssel für die Signatur ausgehender Webhooks erzeugen
- **Wie:** In PowerShell ausführen (eine Zeile):
  ```powershell
  cd C:\Users\WAVO\Desktop\Projekte\agor\apps\backend
  python -c "from nacl.signing import SigningKey; import base64; print(base64.b64encode(SigningKey.generate().encode()).decode())"
  ```
- **Output:** ein ~44-Zeichen base64-String, z.B. `nq0v0p8...=`
- **Wo eintragen:** `apps/backend/.env` (gitignored!), Zeile `AGORA_SIGNING_PRIVATE_KEY_B64=...`
- **Auch setzen:** `AGORA_SIGNING_KEY_ID=agora-2026-05` (oder anderer Identifier)
- **Warum nur du:** der Schlüssel darf nie ins Repo, nicht in den Chat, nirgendwohin außer in `.env` auf Servern, die du kontrollierst
- **Wenn du das nicht machst:** beim ersten Start generiert das Backend einen ephemeren Schlüssel und ändert den Public Key bei jedem Neustart — Empfänger könnten ihn nicht cachen
