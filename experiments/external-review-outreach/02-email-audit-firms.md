# Email outreach to audit firms

## Template

**Subject:** Pre-mainnet drive-by review request — AgoraEscrowV2 (361 LoC, Base Sepolia)

**Body:**

```
Hi [Firm],

I'm Andreas, the solo founder of Agora — an open marketplace protocol
where AI agents discover, hire, and pay other agents via HTTP-402 USDC
escrow on Base. V2 escrow contract is live on Base Sepolia today;
ownership is on a 2-of-2 Gnosis Safe; 14 audit findings from V1 have
been addressed; a 24h timelock design is committed and awaiting review.

Two asks, in order of preference:

1. Would you be willing to do a free preliminary review of the V2
   contract (361 lines, OZ 5.0.2)? I know full audits are typically in
   the 20-50k+ range, which I cannot fund as a solo bootstrapped
   founder. A drive-by review with public credit in our
   SECURITY_REVIEW.md and commit messages would be enormously valuable.

2. If not free, what's your minimum-scope engagement? I have a very
   small budget if there's a focused-issue deep-dive option.

Links:

- Repository: https://github.com/agoraproto/agora
- External review issue (pinned): https://github.com/agoraproto/agora/issues/1
- Review request doc: https://github.com/agoraproto/agora/blob/main/EXTERNAL_REVIEW_REQUEST.md
- Live V2 state: https://github.com/agoraproto/agora/blob/main/apps/backend/docs/V2_LIVE_STATE.md
- Timelock proposal: https://github.com/agoraproto/agora/blob/main/contracts/TIMELOCK_DESIGN.md
- V2 contract: https://sepolia.basescan.org/address/0x0e8E6A760c76cA92c5C5dA06d293E33f1B5fbAEc#code

Happy to scope this any way that works for you, including async-only,
or with NDA, or with a fixed-time cap.

Best,
Andreas
hello@agoraproto.org
```

## Firm shortlist

| Firm | Contact | Notes |
|---|---|---|
| Trail of Bits | contact@trailofbits.com | Top-tier, very busy, often declines small/free. Worth one shot. |
| Cyfrin | https://cyfrin.io/contact | Community-friendly (Patrick Collins). Has done smaller engagements. |
| OpenZeppelin | https://openzeppelin.com/security-audits/ | Top-tier. Likely no-free-review but template firm to ask. |
| Spearbit | https://spearbit.com/ | Boutique, sometimes does scoped reviews. |
| Hacken | https://hacken.io/services/ | Larger, more accessible price points. |
| ChainSecurity | contact@chainsecurity.com | Strong reputation, formal. |
| Halborn | https://halborn.com/contact/ | Mid-tier, sometimes flexible. |
| Quantstamp | https://quantstamp.com/ | Established, formal. |
| Code4rena | contact via twitter @code4rena | Crowdsourced contest model — not a normal "ask for free review" but they sometimes host small protocols pro-bono. |

## Order to try

1. Cyfrin first — most likely to respond positively to a public-credit-only ask
2. Spearbit second — sometimes have idle researchers
3. Trail of Bits and OpenZeppelin third — set expectations very low
4. Hacken, ChainSecurity, Halborn fourth wave
