# ADR — M-V2-01 / M-V2-02 / Timelock-Carve-Outs für V2.1

**Status:** Proposal. Sprint 46, 2026-06-06.
**Author:** Andreas (via internal review).
**Supersedes:** Open items in `SECURITY_REVIEW_V2.md` §3 + `TIMELOCK_DESIGN.md` §4 / §5.
**Blocks:** V2.1 contract spike (Sprint 47), Mainnet deployment.

## Kontext

`AgoraEscrowV2` läuft seit Sprint 35e auf Base Sepolia. Der interne
Self-Audit (Sprint 39) hat zwei MEDIUM-Findings im Contract dokumentiert,
die alle den Eigentümer (Owner) auf den **kritischen Pfad** stellen,
obwohl er nur **Eskalationspfad** sein sollte:

- **M-V2-01** — Stuck-Submitted-Job zwingt Owner zu `resolveDispute`,
  wenn der Payer schlicht langsam ist.
- **M-V2-02** — Spät-eingereichte Garbage-Submits umgehen den sauberen
  `refundExpired`-Pfad und zwingen Payer zu `dispute` → Owner.

Zusätzlich produziert die Sprint-45-Timelock-Landung **zwei
Folge-Regressionen**, die mit V2.1 gelöst werden sollen:

- **T-V2.1-01** — `pause()` läuft jetzt durch den 24h-Timelock.
  Mitigation per `RUNBOOK_PERMANENT_PAUSE_QUEUE.md` ist operationell
  fragil und für Mainnet unzureichend.
- **T-V2.1-02** — `resolveDispute()` läuft jetzt auch durch den 24h-
  Timelock. Disputes brauchen mit Operator-Arbeit + Timelock-Delay
  insgesamt > 24h zur Auflösung — Mainnet-untauglich.

Diese vier Punkte sind die Mainnet-Blocker. Dieses ADR legt die
Entscheidung pro Punkt fest und definiert den V2.1-Patch-Scope.

---

## Entscheidung

### M-V2-01 — Stuck-Submitted-Pfad

**Decision: Patch.** V2.1 fügt eine `payeeForceApprove(jobId)`-Funktion
hinzu, callable durch `j.payee` nach `j.deadline + FORCE_APPROVE_GRACE`.

```solidity
uint256 public constant FORCE_APPROVE_GRACE = 7 days;

function payeeForceApprove(uint256 jobId) external nonReentrant {
    Job storage j = jobs[jobId];
    if (j.payee != msg.sender) revert NotPayee();
    if (j.status != JobStatus.Submitted) revert InvalidStatus();
    if (block.timestamp <= j.deadline + FORCE_APPROVE_GRACE) revert DeadlineNotElapsed();
    _settleApproval(j, jobId);   // shared with approveAndPay
    emit JobApprovedByPayeeForce(jobId, msg.sender);
}
```

**Begründung.**
- Bewahrt die "späte Approval grace" Design-Wahl (Sprint 35 H-03) für
  benigne Payer.
- Gibt dem Payee einen on-chain Eskalations-Pfad, der nicht den
  Owner-Schreibtisch durchläuft.
- 7 Tage Grace genügen für realistische Internet-Probleme + Urlaub
  des Payers.
- Wert-Risiko für Payer ist asymmetrisch: er hatte 7 Tage über die
  Deadline hinaus Zeit zu approven oder zu disputen. Wenn er weder
  noch macht, ist sein Schweigen Zustimmung.

**Risiko.** Ein Provider, der wissentlich Mist abliefert, kann nach
7 Tagen Payer-Schweigen self-payen. Mitigation: Payer hat in jedem
Fall den `dispute()`-Knopf, der die Zeit auf "owner-resolve" stoppt.
`payeeForceApprove` schreitet **nur in `Submitted`**, nicht in
`Disputed` voran.

### M-V2-02 — Late-Garbage-Submit DoS

**Decision: Patch.** V2.1 erweitert `refundExpired` um den Pfad für
`Submitted`-Jobs.

```solidity
uint256 public constant PAYER_FORCE_REFUND_GRACE = 3 days;

function refundExpired(uint256 jobId) external nonReentrant {
    Job storage j = jobs[jobId];
    if (j.status == JobStatus.Funded) {
        if (block.timestamp <= j.deadline) revert DeadlineNotElapsed();
        _settleRefund(j, jobId);
        return;
    }
    if (j.status == JobStatus.Submitted) {
        if (msg.sender != j.payer) revert NotPayer();
        if (block.timestamp <= j.deadline + PAYER_FORCE_REFUND_GRACE) {
            revert DeadlineNotElapsed();
        }
        _settleRefund(j, jobId);
        return;
    }
    revert InvalidStatus();
}
```

**Begründung.**
- Wenn der Payee Garbage submitted, hat der Payer 3 Tage post-Deadline
  Zeit zu reagieren — entweder approven (= akzeptieren), disputen
  (= eskalieren) oder schweigen (= force-refund).
- 3 Tage ist die symmetrische Antwort auf 7 Tage für den Payee in
  M-V2-01: Payer hat den kürzeren Grace, weil er aktiv "Garbage
  empfangen" hat und früher reagieren sollte.
- Restricting auf `msg.sender == j.payer` verhindert dass ein Dritter
  den Payee bei legitimen aber langsamen Disputes überläuft.

**Risiko.** Payee submitted ehrliche Arbeit, Payer ist 4 Tage off-line.
Payee verliert die Forderung. Mitigation: Payee kann **bis zur Deadline**
oder via `payeeForceApprove` (siehe M-V2-01) nach `deadline + 7 days`
trotzdem zahlen. Window für diesen Edge-Case: `deadline + 3d` bis
`deadline + 7d`, also 4 Tage. Wenn der Payer in dem Fenster
force-refundet, **verliert der Payee diese Forderung permanent**.

Das ist akzeptabel, weil:
- Der Payee hatte bereits bis zur Deadline Zeit, was anderes als
  Garbage zu submitten;
- Der Payer hat aktiv die Bewertung getroffen "das war Garbage"
  bevor er force-refundet;
- Bei ehrlichen Streitigkeiten ist `dispute()` der richtige Pfad.

### T-V2.1-01 — `pause()` braucht direkten Safe-Pfad

**Decision: Patch.** V2.1 fügt eine separate `pauser`-Rolle ein,
die direkt vom Safe gehalten wird (Option A aus
`TIMELOCK_DESIGN.md` §4).

```solidity
address public pauser;

modifier onlyPauserOrOwner() {
    if (msg.sender != pauser && msg.sender != owner()) revert Unauthorized();
    _;
}

function pause() external onlyPauserOrOwner { _pause(); }
function unpause() external onlyOwner { _unpause(); }

function setPauser(address _pauser) external onlyOwner {
    if (_pauser == address(0)) revert InvalidAddress();
    address old = pauser;
    pauser = _pauser;
    emit PauserUpdated(old, _pauser);
}
```

**Architektur post-Deploy:**

```
Safe 2-of-2 ─┬─[ pauser ]─────────────────> V2.1.pause()   (instant)
             └─[ proposer/executor ]─> Timelock ─[ owner ]─> V2.1.*    (24h delay)
```

**Begründung.**
- `pause()` ist der Notfall-Knopf. 24h Verzögerung ist
  Operationally inakzeptabel.
- `unpause()` bleibt hinter Timelock, weil deliberate Restart langsam
  sein sollte.
- `setPauser` ist owner-only (= Timelock), also kann ein kompromittierter
  pauser nur pausen, nicht weiter gegeben werden.

### T-V2.1-02 — `resolveDispute` braucht direkten Safe-Pfad

**Decision: Patch.** V2.1 fügt eine separate `disputeResolver`-Rolle
ein, die direkt vom Safe gehalten wird.

```solidity
address public disputeResolver;

modifier onlyResolverOrOwner() {
    if (msg.sender != disputeResolver && msg.sender != owner()) revert Unauthorized();
    _;
}

function resolveDispute(
    uint256 jobId,
    uint256 payeeAmount,
    uint256 payerAmount
) external onlyResolverOrOwner nonReentrant { ... }

function setDisputeResolver(address _r) external onlyOwner {
    if (_r == address(0)) revert InvalidAddress();
    address old = disputeResolver;
    disputeResolver = _r;
    emit DisputeResolverUpdated(old, _r);
}
```

**Begründung & Trust-Modell.**

`resolveDispute` ist ein **Trust-Anker**, kein Notfall-Knopf. Es teilt
Geld zwischen zwei Parteien. Das ist genau die Funktion, die ein
zukünftiges Oracle / 2-of-3 Arbitrator-Pattern (TIMELOCK_DESIGN.md §5)
ersetzen soll.

Bis dahin ist der Safe der einzige existierende Trust-Anker. Es ist
**besser**, `resolveDispute` direkt am Safe zu lassen (= schnell,
aber Safe-vertraut) als hinter Timelock zu sperren (= langsam UND
Safe-vertraut, weil der Safe nach 24h sowieso ausführt).

`setDisputeResolver` ist owner-only (= Timelock), also braucht eine
**Änderung** des Resolvers 24h Bedenkzeit. Das ist die Asymmetrie,
die hier Sicherheit bringt: Resolver ist schnell, aber Resolver-Wechsel
ist langsam.

---

## Open Items, die das ADR NICHT entscheidet

1. **Trustless `resolveDispute`** über Oracle / 2-of-3-Arbitrator —
   bleibt für Sprint 50+ (Mainnet-Phase). V2.1 bringt nur die
   Rollen-Trennung, nicht die Trust-Reduktion.

2. **Pauser-Rotation-Policy** — wie schnell wird `setPauser` benutzt,
   wenn der pauser-Key kompromittiert ist? Operational, nicht Contract.

3. **Force-Approve / Force-Refund Window-Tuning** — 7d / 3d sind
   Anfangswerte. Wenn der Swarm-Traffic zeigt, dass benigne Payer
   im Schnitt > 7d brauchen, müssen wir hoch. Empirisch, nicht
   ADR-Frage.

4. **Backwards-Compatibility V2 → V2.1** — alle alten V2-Jobs werden
   weiterlaufen ohne Migration; V2.1 ist ein neuer Vertrag an neuer
   Adresse mit allen V2-Hardenings plus den vier oben genannten
   Patches. Backend muss V1/V2/V2.1 wie schon V1/V2 dispatchen.

---

## Konsequenzen, wenn dieses ADR angenommen wird

1. **Sprint 47 (V2.1 Contract-Spike)** kann starten:
   - `payeeForceApprove` + `refundExpired` Extension
   - `pauser` + `disputeResolver` Rollen + Setter
   - Tests gegen alle vier Patches
   - Migration-Tests für V2 → V2.1 Backend-Dispatch

2. **Sprint 48 (MAINNET_MIGRATION_RUNBOOK.md)** kann auf V2.1
   verweisen statt auf V2.

3. **Externes Audit** wird auf V2.1 fokussiert, nicht V2 — V2 bleibt
   Sepolia-Testnet-Artefakt.

4. **Timelock Option A** wird damit obsolet — Option B + V2.1 zusammen
   geben uns die gleiche Sicherheits-Eigenschaft (pause direkt, alles
   andere mit Delay) ohne den V2-Contract anzufassen.

---

## Was angenommen werden muss

Andreas (Owner). Wenn dieses ADR angenommen ist:

- [ ] **M-V2-01 Patch:** `payeeForceApprove`, 7d Grace
- [ ] **M-V2-02 Patch:** `refundExpired` für `Submitted`, 3d Grace
- [ ] **T-V2.1-01 Patch:** separate `pauser`-Rolle
- [ ] **T-V2.1-02 Patch:** separate `disputeResolver`-Rolle

Andere mögliche Varianten, die dieses ADR **nicht** wählt:

- Stricter H-03: `approveAndPay` würde nach Deadline reverten —
  zu unfreundlich für gutmeinende langsame Payer.
- M-V2-02 via `submitResult` zeitlich beschränkt (z.B. nur in den
  ersten 90% der Job-Laufzeit) — bricht legitime Last-Minute-Submits.
- T-V2.1-01 / T-V2.1-02 ohne separate Setter, sondern fest verdrahtet
  auf den Safe — zerstört die Rotierbarkeit bei Schlüsselkompromiss.
