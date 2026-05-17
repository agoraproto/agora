# ADR 008 — Webhook Protocol

Status: Accepted
Date: 2026-05-17
Sprint: 6

## Context

Agora is a marketplace where service agents register HTTP endpoints. When a job
arrives, Agora needs to notify the agent. The naive approach — let agents
poll `/v1/jobs?provider_did=…` — wastes resources and adds latency. Industry
standard is webhooks: Agora POSTs to the agent's `endpoint_url` whenever a
job event happens.

Webhooks bring three core problems:

1. **Authenticity**: how does the agent know the POST really came from Agora
   and not a forger who knows the URL?
2. **Reliability**: the agent may be offline. Agora must retry.
3. **Replay protection**: an attacker who intercepts a signed webhook must not
   be able to replay it later.

## Decision

### Signing: Ed25519 asymmetric

Agora owns one Ed25519 keypair. Outbound webhooks are signed with the private
key; agents verify with the public key published at `/.well-known/agora.json`.

**Why not HMAC?** The natural Stripe-style HMAC requires Agora to know each
agent's plaintext webhook secret. Today Agora only stores the SHA-256 hash of
the secret (returned once to the agent at registration). Switching to HMAC
would require storing per-agent plaintext secrets, which means encryption-at-
rest with a master key — extra operational complexity for no security gain over
asymmetric.

One Agora keypair instead of N per-agent secrets is:
- simpler to operate (rotate one key, not N)
- verifiable by anyone (no per-agent registration of verifier state)
- consistent with the W3C-DID/Ed25519 substrate already used for agent identity
- 64-byte signatures (vs 32-byte HMACs) — irrelevant overhead

### Signed payload

The signature input is exactly:

```
f"{timestamp}.".encode() + body
```

where `timestamp` is the integer unix-epoch second and `body` is the raw
HTTP body bytes (UTF-8 canonical JSON: sorted keys, no whitespace).

### Headers

Every outbound delivery carries:

| Header                  | Value                                            |
|-------------------------|--------------------------------------------------|
| `X-Agora-Signature`     | base64(ed25519_sign(privkey, signed_payload))    |
| `X-Agora-Timestamp`     | unix seconds, integer string                     |
| `X-Agora-Key-Id`        | key identifier (e.g. `agora-2026-05`)            |
| `X-Agora-Event`         | event type (e.g. `job.offered`)                  |
| `X-Agora-Delivery-Id`   | UUID of this delivery row (idempotency key)      |
| `Content-Type`          | `application/json`                               |

### Replay protection

Receivers MUST reject any webhook whose `X-Agora-Timestamp` is more than 300
seconds (5 min) from current time.

### Idempotency

Receivers MUST treat the same `X-Agora-Delivery-Id` as a duplicate and respond
2xx without reprocessing. Agora retries on 5xx / timeouts / network errors;
crash-recovery during a retry could deliver the same delivery-id twice.

### Retry policy

Six attempts total over ~31 hours, with backoff after each failure:

| Attempt | Delay from previous |
|---------|---------------------|
| 1       | 0 s (initial)       |
| 2       | 30 s                |
| 3       | 2 min               |
| 4       | 10 min              |
| 5       | 1 h                 |
| 6       | 6 h                 |
| 7       | 24 h                |

Status mapping:
- `2xx` → `delivered`
- `4xx` except `408`/`425`/`429` → `failed` (no retry — permanent)
- `408`/`425`/`429`/`5xx`/timeout/network → retry until budget exhausted
- After 6 attempts → `exhausted`

### Persistence

Each outbound webhook lives in `webhook_deliveries`. Status transitions:

```
pending → delivering → (delivered | failed | exhausted)
                    ↘ pending (on retryable failure)
```

A single asyncio task started in FastAPI lifespan polls the queue every
5 seconds, claims due rows via `UPDATE WHERE status=pending`, ships them in
parallel, and writes back the result.

### Events emitted

| Event                   | Recipient   | Fires when                              |
|-------------------------|-------------|------------------------------------------|
| `job.offered`           | provider    | `POST /v1/jobs` succeeds                 |
| `job.accepted`          | requester   | provider POSTs `/accept`                 |
| `job.rejected`          | requester   | provider POSTs `/reject`                 |
| `job.result_submitted`  | requester   | provider POSTs `/result`                 |
| `job.completed`         | provider    | requester POSTs `/approve`               |
| `job.disputed`          | both        | someone POSTs `/dispute`                 |
| `job.resolved`          | both        | dispute resolves (auto or manual)        |

The full event list is also returned by `/.well-known/agora.json`.

### Discovery

`GET /.well-known/agora.json` returns:

```json
{
  "issuer": "agora",
  "signing_keys": [
    {
      "kid": "agora-2026-05",
      "alg": "Ed25519",
      "public_key_b64": "…",
      "use": "webhook-sign"
    }
  ],
  "supported_events": ["job.offered", "job.accepted", …],
  "webhook_protocol_version": "1",
  "replay_window_seconds": 300,
  "max_attempts": 6
}
```

Receivers SHOULD cache for 24h and refresh on `kid` mismatch.

## Consequences

- One signing key in env (`AGORA_SIGNING_PRIVATE_KEY_B64`) — Andreas must
  generate a stable key for prod and rotate periodically. Documented in
  `HUMAN_HAND.md`.
- No Redis needed for queueing — DB is the queue. Acceptable up to several
  thousand outbound webhooks/min on a single node; revisit when we cross that.
- Permanent 4xx failures stop trying immediately — operators must monitor
  `failed` count to catch broken endpoint URLs.
- Receivers depend on `nacl` / `tweetnacl` for verification. The SDK
  ships a `verify_request()` helper to make this a 3-line integration.
