# experiments/external-review-outreach

Templates and shortlists for actively soliciting external review of
the AgoraEscrowV2 contract pre-mainnet. The strategy across all four
channels is the same: drive-by review, public credit only, no budget.

## Files

- **`01-twitter-dm-solo-auditors.md`** — direct DM template for known
  solo Solidity researchers. Highest hit rate per attempt, lowest reach
  per message. Start here.
- **`02-email-audit-firms.md`** — formal email template for audit
  firms (Cyfrin, Spearbit, Trail of Bits, OpenZeppelin etc.). Lowest
  hit rate but worth one shot per firm.
- **`03-twitter-public-post.md`** — five-tweet thread for the public
  account. Maximises reach; quality of responses is unpredictable.
- **`04-discord-telegram-posts.md`** — informal community-channel
  posts (SecureumDAO, Cyfrin, Code4rena, etc.).

## Suggested order

1. **Week 1**: post the Twitter thread (template 3), pin it on the
   project account. Concurrently DM 3-5 solo auditors (template 1).
2. **Week 1**: post in 2-3 community channels (template 4).
3. **Week 2**: if response is thin, email 3 audit firms (template 2)
   starting with Cyfrin and Spearbit.
4. **Week 3+**: follow up with no-responses ONCE, then move on.

## Anchor: the central pinned Issue

Every outreach links back to
https://github.com/agoraproto/agora/issues/1 which has the full
review request, scope, and how to submit findings. Keep that issue
fresh — every time we do a significant migration (like Sprint 37 Safe
or Sprint 39 Timelock), add an update comment.

## What's already in place

- ✓ Pinned Issue #1 with full scope (Sprint 35b)
- ✓ EXTERNAL_REVIEW_REQUEST.md committed at repo root
- ✓ Sprint 37 Safe migration update commented on Issue #1 (Sprint 37d)
- ✓ V2_LIVE_STATE.md (Sprint 38b) for reviewers who want
  concrete numbers
- ✓ TIMELOCK_DESIGN.md (Sprint 38c) for reviewers who want to comment
  on planned hardening

## What's NOT in place yet

- Actual outreach sent (this folder's templates haven't been used)
- Mainnet timeline commitment (still "pre-mainnet, no date")
- Bug bounty budget (still 0)

## Tracking responses

When a reviewer engages, log them in `SECURITY_REVIEW.md` (in the
repo root). Format:

```
## Findings

### F-NN: <title>
- Reviewer: <handle / firm>
- Submitted: YYYY-MM-DD
- Status: accepted | wontfix | out of scope
- Severity: H | M | L | info
- Fix commit: <sha>
```
