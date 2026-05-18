import { describe, it, expect } from "vitest";
import * as ed25519 from "@noble/ed25519";
import { verifyRequest, SignatureInvalid } from "../src/webhooks.js";

function bytesToB64(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes));
}

describe("verifyRequest", () => {
  it("accepts a freshly-signed request", async () => {
    const priv = ed25519.utils.randomPrivateKey();
    const pub = await ed25519.getPublicKeyAsync(priv);
    const ts = Math.floor(Date.now() / 1000);
    const body = new TextEncoder().encode('{"hello":"world"}');
    const payload = new Uint8Array(`${ts}.`.length + body.length);
    payload.set(new TextEncoder().encode(`${ts}.`), 0);
    payload.set(body, `${ts}.`.length);
    const sig = await ed25519.signAsync(payload, priv);

    await expect(
      verifyRequest(bytesToB64(pub), bytesToB64(sig), ts, body),
    ).resolves.toBeUndefined();
  });

  it("rejects a stale timestamp", async () => {
    const priv = ed25519.utils.randomPrivateKey();
    const pub = await ed25519.getPublicKeyAsync(priv);
    const ts = Math.floor(Date.now() / 1000) - 9999;
    const body = new TextEncoder().encode("{}");
    const sig = await ed25519.signAsync(new Uint8Array(), priv);

    await expect(
      verifyRequest(bytesToB64(pub), bytesToB64(sig), ts, body),
    ).rejects.toThrow(SignatureInvalid);
  });

  it("rejects a tampered body", async () => {
    const priv = ed25519.utils.randomPrivateKey();
    const pub = await ed25519.getPublicKeyAsync(priv);
    const ts = Math.floor(Date.now() / 1000);
    const body = new TextEncoder().encode('{"hello":"world"}');
    const payload = new Uint8Array(`${ts}.`.length + body.length);
    payload.set(new TextEncoder().encode(`${ts}.`), 0);
    payload.set(body, `${ts}.`.length);
    const sig = await ed25519.signAsync(payload, priv);

    const tampered = new TextEncoder().encode('{"hello":"tampered"}');
    await expect(
      verifyRequest(bytesToB64(pub), bytesToB64(sig), ts, tampered),
    ).rejects.toThrow(SignatureInvalid);
  });

  it("rejects malformed base64", async () => {
    const ts = Math.floor(Date.now() / 1000);
    await expect(
      verifyRequest("not-valid-base64!!!", "also-bad!!!", ts, new Uint8Array()),
    ).rejects.toThrow(SignatureInvalid);
  });
});
