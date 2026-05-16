# ADR 004 – Gebührenmodell

- **Datum:** 2026-05-16
- **Status:** Aktiv
- **Bezug:** Spec §6.5 / §14.1, Review §2.2 (Unit Economics)

## Entscheidung

```
Plattform-Fee  =  max( 0,50 €, min( 25 €, 1,0 % × Auftragswert ) )
```

### Klartext

- **1,0 % Plattform-Fee** vom Auftragswert
- **Mindestens 0,50 €** pro Transaktion (deckt Infrastruktur + Gas-Anteil bei Onchain-Phase)
- **Höchstens 25 €** pro Transaktion (Großauftrags-Cap; verhindert, dass Plattform unverhältnismäßig viel an einer einzelnen TX verdient)

### Wirkungsanalyse

| Auftragswert | 1 % | Effektive Fee | Effektiver % |
|---|---|---|---|
| 0,10 € | 0,001 € | **0,50 €** (Min) | 500 % (Mikro-TX unattraktiv – gewollt) |
| 1,00 € | 0,01 € | **0,50 €** | 50 % |
| 10,00 € | 0,10 € | **0,50 €** | 5 % |
| 50,00 € | 0,50 € | **0,50 €** | 1 % |
| 100,00 € | 1,00 € | **1,00 €** | 1 % |
| 500,00 € | 5,00 € | **5,00 €** | 1 % |
| 1.000,00 € | 10,00 € | **10,00 €** | 1 % |
| 2.500,00 € | 25,00 € | **25,00 €** (Cap) | 1 % |
| 10.000,00 € | 100,00 € | **25,00 €** (Cap) | 0,25 % |
| 100.000,00 € | 1.000,00 € | **25,00 €** (Cap) | 0,025 % |

### Konsequenzen aus diesem Modell

✅ **Mikro-TX (< 5 €)** werden durch Mindest-Fee teuer → bewusste Lenkung weg von Cent-Operationen, die der Spec §14.3 entstammen. Spart Infrastruktur-Last.
✅ **Mittlere TX (5–2.500 €)** sind der **Sweet Spot** – 1 % effektiv. Hier liegt der echte Geschäftswert für Agora.
✅ **Großauftrags-Cap (25 €)** macht Agora für Enterprise-Beträge wettbewerbsfähig (Stripe wäre bei 100.000 € auf 2.900 € + 0,30 €).
⚠ **Spec §14.3 Unit Economics** muss umgeschrieben werden: Annahme „Ø 0,10 € TX" entfällt — realistischer Sweet-Spot ist 5–50 € TX.

## Aufteilung der Fee

Aus der vereinnahmten Fee:

| Position | Anteil | Begründung |
|---|---|---|
| Versicherungspool | **10 %** der Fee | Spec §6.7 / §21.1: 0,1 % vom Auftragswert ≈ 10 % der 1 %-Fee |
| Plattform-Operations | **90 %** der Fee | Infra, Personal, Gas-Anteil bei Onchain-Phase |

### Beispielrechnung 10 € Auftrag

- Fee: 0,50 € (= Mindestbetrag, da 1 % wäre nur 0,10 €)
- → 0,05 € → Versicherungspool
- → 0,45 € → Plattform
- Agent erhält: 9,50 €

### Beispielrechnung 1.000 € Auftrag

- Fee: 10,00 € (1 %)
- → 1,00 € → Versicherungspool
- → 9,00 € → Plattform
- Agent erhält: 990,00 €

### Beispielrechnung 10.000 € Auftrag (Cap greift)

- Fee: 25,00 € (Cap)
- → 2,50 € → Versicherungspool
- → 22,50 € → Plattform
- Agent erhält: 9.975,00 €

## Bootstrap-Phase

Solange Off-Chain-Ledger (ADR 003): Fees werden nur als interne Buchung berechnet, nicht abgezogen. Das ermöglicht Testflüsse ohne realen Geldverkehr und schult uns auf das Modell.

## Anpassbarkeit

Fee-Parameter sind in Smart-Contract (Onchain-Phase) und Backend-Settings hinterlegt und können durch Owner geändert werden — aber **mit Hard-Cap auf 2 %** (siehe Spec §5.3: „niemals höher als 1 %" wird auf 2 % gelockert für sehr kleine TX, da der Mindestbetrag dieselbe Wirkung hat).

## Klärungspunkt für Andreas

Sind die Stufen 0,50 € / 25 € langfristig richtig oder wollen wir sie als Parameter regelmäßig (z. B. jährlich) gegen Marktbenchmarks prüfen?

→ **Vorschlag:** jährliche Review. Bis dahin: festgenagelt.
