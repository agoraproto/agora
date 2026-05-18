/**
 * Webhook verification for receivers (ADR 008).
 *
 * Service agents subscribed to Agora webhooks should call `verifyRequest`
 * on each incoming POST. Agora's signing public key is published at
 * https://api.agoraproto.org/.well-known/agora.json - cache it for ~24h.
 *
 * Usage with any HTTP framework:
 *
 *   import { verifyRequest, SignatureInvalid } from "@agora/sdk";
 *
 *   const sig = req.header("X-Agora-Signature");
 *   const ts  = req.header("X-Agora-Timestamp");
 *   const body = await readRawBody(req); // bytes, not parsed JSON
 *
 *   try {
 *     await verifyRequest(AGORA_PUBKEY_B64, sig, ts, body);
 *   } catch (e) {
 *     return res.status(401).send(String(e));
 *   }
 */

import * as ed25519 from "@noble/ed25519";

export class SignatureInvalid extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = "SignatureInvalid";
  }
}

function b64ToBytes(b64: string): Uint8Array {
  // Accepts both standard and url-safe base64.
  const normalized = b64.replace(/-/g, "+").replace(/_/g, "/");
  const pad = normalized.length % 4 === 0 ? "" : "=".repeat(4 - (normalized.length % 4));
  const bin = atob(normalized + pad);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/**
 * Verify an Agora webhook. Throws SignatureInvalid on any problem.
 *
 * @param publicKeyB64  Agora's signing pubkey (from /.well-known/agora.json)
 * @param signatureB64  value of X-Agora-Signature header
 * @param timestamp     value of X-Agora-Timestamp header (unix seconds)
 * @param body          raw request body bytes (do NOT re-encode JSON)
 * @param maxAgeSeconds reject anything older than this (replay protection)
 */
export async function verifyRequest(
  publicKeyB64: string,
  signatureB64: string,
  timestamp: number | string,
  body: Uint8Array,
  maxAgeSeconds: number = 300,
): Promise<void> {
  const ts = typeof timestamp === "string" ? parseInt(timestamp, 10) : timestamp;
  if (!Number.isFinite(ts)) {
    throw new SignatureInvalid(`invalid timestamp: ${timestamp}`);
  }

  const age = Math.abs(Math.floor(Date.now() / 1000) - ts);
  if (age > maxAgeSeconds) {
    throw new SignatureInvalid(`timestamp ${ts} too old (age=${age}s, max=${maxAgeSeconds}s)`);
  }

  let pub: Uint8Array;
  let sig: Uint8Array;
  try {
    pub = b64ToBytes(publicKeyB64);
    sig = b64ToBytes(signatureB64);
  } catch (e) {
    throw new SignatureInvalid(`malformed signature or pubkey: ${e}`);
  }

  // signed payload: "${ts}." + body (bytes)
  const prefix = new TextEncoder().encode(`${ts}.`);
  const payload = new Uint8Array(prefix.length + body.length);
  payload.set(prefix, 0);
  payload.set(body, prefix.length);

  let ok: boolean;
  try {
    ok = await ed25519.verifyAsync(sig, payload, pub);
  } catch (e) {
    throw new SignatureInvalid(`signature verification error: ${e}`);
  }

  if (!ok) {
    throw new SignatureInvalid("signature does not verify");
  }
}
