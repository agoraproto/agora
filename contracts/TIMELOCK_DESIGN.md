# Timelock Design for AgoraEscrowV2

**Status:** design proposal (Sprint 38c, 2026-06-01). Not yet implemented.
**Target deploy:** Sprint 39+ (after external review of this design).

## 1. Goal

Today V2 is controlled by a 2-of-2 Gnosis Safe
(`0x8Ec63Fe30DAb84308B5009b8D91d9E4dEB5a61FC`). The Safe can execute any
admin call on V2 _instantly_ once both cosigners sign. That is acceptable
for testnet practice but unacceptable for Mainnet: if both cosigner keys
are compromised — or if a single cosigner colludes with whoever holds the
other key — the attacker can immediately drain fees to themselves
(`setFeeRecipient`), or arbitrarily reassign job escrow
(`resolveDispute`), with zero delay for users to exit.

A Timelock between Safe and V2 puts a **mandatory cooling-off window**
between any admin proposal and its execution, during which third parties
can:

- Observe the proposal on-chain (it's a public `schedule` event).
- Cancel it (if the Safe still has the canceller role).
- For users: exit any positions held in the V2 escrow before the change
  lands.

The Timelock is not a substitute for a good multisig; it is an
**additional layer** on top of it.

## 2. Threat model — what the Timelock buys us

| Threat | Without Timelock | With Timelock |
|---|---|---|
| Both cosigner keys leaked → attacker drains fees via `setFeeRecipient` | Instant loss | 24 h window for legitimate Safe operator to (a) revoke leaked keys via `addOwner`+`removeOwner`, or (b) cancel the malicious `schedule` |
| Single cosigner colludes with the other key holder | Instant attack | Same 24 h public window before execution |
| Honest admin error (typo in fee parameter, wrong recipient address) | Instant; on-chain rollback requires another admin tx | 24 h to spot the mistake and cancel before it lands |
| Forced "stop the protocol" exploit response (e.g. discovered bug) | Instant `pause()` is essential | **Conflict — Timelock would delay emergency pause too.** Resolved by carving `pause()` out, see §4. |

## 3. Per-function recommendation

V2 admin entry points:

| Function | Behind Timelock? | Reasoning |
|---|---|---|
| `setFees(feeBps, minFee, maxFee, insuranceShareBps)` | YES (24 h) | Revenue impact, easily observable, no operational urgency. The contract enforces caps (MAX_FEE_BPS=500, MAX_INSURANCE_SHARE_BPS=5000) so even a malicious proposal can't grant unbounded fees. |
| `setFeeRecipient(address)` | YES (24 h) | Direct drain vector. Highest-leverage attack on a compromised admin. Must have delay. |
| `setInsurancePool(address)` | YES (24 h) | Same drain vector via the insurance share. |
| `transferOwnership(address)` | YES (24 h) | Permanent loss of control if pointed at attacker. Combined with `Ownable2Step` (V2's pattern), this is already 2 txs, but Timelock adds the cool-off. |
| `unpause()` | YES (24 h) | Resuming protocol operations should be deliberate. If the pause was triggered to respond to an exploit, 24 h gives time to verify the fix landed before traffic resumes. |
| `resolveDispute(jobId, payeeAmt, payerAmt)` | **NO** — but with caveats, see §5 | Disputes have a deadline; legitimate users need fast resolution. Timelock would freeze any disputed escrow for 24 h+. |
| `pause()` | **NO** — emergency path, see §4 | Emergency response must be instant. Timelocking pause defeats its purpose. |
| `acceptOwnership()` (Ownable2Step) | NO | Called BY the new owner address to accept; if Timelock is the new owner, the Timelock itself executes this via its `execute()` flow, which is naturally the post-delay path. |

**Net result:** 5 of 8 admin entry points go behind a 24 h timelock; 1
stays direct (pause); 1 stays direct but is otherwise scoped down
(resolveDispute, see §5); 1 is naturally subsumed (acceptOwnership).

## 4. The pause() carve-out

`pause()` must remain instant. There are two ways to achieve this with an
OZ `TimelockController`-style timelock as the V2 owner:

### Option A — give the Safe a separate "pauser" role on V2 (RECOMMENDED)

Add a `pauser` role to V2 that's distinct from `owner`. The Safe is
**both** the pauser (direct) and the proposer for the Timelock (which
becomes the new owner). The on-chain ownership chain looks like:

```
                 [ Safe 2-of-2 ]
                  /         \
                 /           \                  
        proposer/             pauser/
        canceller             unpauser (if separated)
        |                    |
   [ Timelock ]              v
        |                directly on V2.pause()
        owner| (the everything-else owner)
        v
       [ V2 ]
```

Pros: clean separation. Pause works instantly; everything else delayed.
Cons: requires a contract update (V2.1) to add the pauser role and route
the pause modifier through it. That's a redeploy with state migration —
a non-trivial sprint.

### Option B — accept that pause goes through the Timelock too

Keep V2 as-is. Timelock owns V2. `pause()` waits 24 h.

Pros: no contract change. Quickest path to a Timelock in production.
Cons: defeats the primary emergency-stop affordance. If a critical bug
is found, the protocol stays exploitable for 24 h while the pause is
"in the queue".

Mitigation if we go Option B: keep a pre-signed Safe proposal for
`pause()` permanently scheduled and re-scheduled every 24 h, so there's
always one within 24 h of executable. This is operationally fragile but
better than nothing.

**Recommendation:** Option A. Plan a V2.1 contract upgrade that adds
the pauser role separation. The current V2 stays in production until
V2.1 is reviewed + deployed; until then, Mainnet should not deploy.

## 5. The resolveDispute carve-out

`resolveDispute(jobId, payeeAmt, payerAmt)` is owner-arbitrated splitting
of an escrow that's gone to `disputed` status. Putting this behind a 24 h
timelock means: dispute resolution takes at least 24 h _after_ the
operator has decided how to split — on top of however long the operator
took to investigate.

For users this is a bad experience. For the operator it gives a 24 h
window to be challenged about a contested split, which is actually a
feature, but the cost is high.

**Recommendation:** leave `resolveDispute` direct for now, but flag this
in the External Review as the function that most needs to be made
trustless before Mainnet (Sprint 40+ candidate: oracle or 2-of-3
arbitrator pattern).

## 6. Delay length: 24 h

Trade-off analysis:

| Delay | Pro | Con |
|---|---|---|
| 12 h | Faster legitimate operations | Too short for the average watcher (timezone-dependent reviewer) to react |
| **24 h** | Industry standard for hardening multisig-owned contracts; gives reviewers across timezones one full day to spot a malicious proposal | Operational friction (admin changes take 24 h to land) |
| 48 h | Safer for less-attended protocols | Doubled friction; rarely the right answer for a 2-of-2 multisig |
| 7 d | DAO-governance level | Overkill — not a DAO, not Mainnet-major-protocol |

**Choice: 24 h.** Established practice, real protection, manageable
operational cost. Easy to extend later if we move to a real DAO.

## 7. Architecture: contracts + roles

We use OpenZeppelin `TimelockController` (audited, widely deployed).

```
TimelockController constructor args:
  minDelay = 86400          // 24 h in seconds
  proposers = [SAFE]        // who can schedule and cancel
  executors = [SAFE]        // who can execute after delay
                            //   (use address(0) for "anyone after delay"
                            //   if we want trustless execution; for
                            //   testnet practice keep it Safe-restricted)
  admin = address(0)        // renounce admin role at deploy
```

`admin = address(0)` makes the Timelock **immutable**: nobody can modify
roles after deploy. This is correct because we want the Timelock's
guarantees to be unforgeable.

Roles in OZ TimelockController:
- `PROPOSER_ROLE` — can call `schedule()` and `scheduleBatch()`
- `EXECUTOR_ROLE` — can call `execute()` after delay
- `CANCELLER_ROLE` — can call `cancel()` on a scheduled-but-not-executed proposal
- `TIMELOCK_ADMIN_ROLE` — can grant/revoke any of the above

By default, anyone granted `PROPOSER_ROLE` also gets `CANCELLER_ROLE`,
which is what we want: the Safe can cancel its own mistakes.

## 8. Ownership migration plan

This is a multi-step move. Each step is reversible until the final one.

### Step 1 (Sprint 39a) — Deploy `TimelockController` with Safe as proposer/executor/canceller, admin renounced

```solidity
new TimelockController(
    86400,                          // 24 h
    [SAFE_ADDRESS],                 // proposers
    [SAFE_ADDRESS],                 // executors
    address(0)                      // admin (renounced)
)
```

Record the Timelock address as `TIMELOCK_ADDRESS`.

### Step 2 (Sprint 39b) — Safe schedules `V2.transferOwnership(TIMELOCK_ADDRESS)`

Wait 24 h.

### Step 3 (Sprint 39c) — Safe executes the scheduled `transferOwnership`

V2.`pendingOwner()` is now the Timelock. V2.`owner()` is still the Safe.

### Step 4 (Sprint 39d) — Safe schedules `TIMELOCK.execute(V2.acceptOwnership())`

This is a re-entry: the Timelock has to call into itself to call into V2.
Construction is fiddly but standard. We schedule the inner call on the
Timelock, wait 24 h, then anyone (in our case, the Safe) executes it.

At this point V2.`owner()` becomes the Timelock. Irreversible.

### Step 5 (Sprint 39e) — Verify and document

Update `V2_LIVE_STATE.md` to show the new ownership chain. Update
`EXTERNAL_REVIEW_REQUEST.md` to reflect the additional layer.

## 9. Open items / not in scope

- **V2.1 with pauser separation (Option A above)** — needs contract
  redesign + audit + redeploy + escrow-balance migration. That's a
  Sprint 40+ project on its own.
- **Trustless dispute resolution** — `resolveDispute` stays admin-only
  for now. Designing an oracle or arbitrator pattern is a separate
  conversation with reviewers.
- **DAO-level governance** — out of scope for testnet. May come post-
  Mainnet once we have a token / voting model worth governing.
- **Mainnet rollout** — depends on (a) this Timelock being deployed and
  tested on testnet first, (b) the external review actually returning
  findings, (c) the V2.1 pause-role separation if we go that way, and
  (d) hardware-wallet cosigners replacing the test cosigners.

## 10. Decision required from the operator

Before we move to Sprint 39 (implementation), the operator needs to
choose:

1. **Pause approach: Option A (V2.1 redeploy with pauser separation) or
   Option B (accept pause delay during the interim)?** Recommendation: A,
   but only after this design has external review.
2. **Executor: Safe-only or address(0) ("anyone after delay")?**
   Recommendation: Safe-only for the testnet practice round, can
   liberalize later.
3. **Delay length: 24 h (recommended) or longer?**
4. **Do we want the Timelock deployment + ownership migration to happen
   before or after we re-engage external reviewers?** Recommendation:
   after, so reviewers see the design first and can comment.

---

_See `V2_LIVE_STATE.md` for the current concrete state of V2 ownership._
