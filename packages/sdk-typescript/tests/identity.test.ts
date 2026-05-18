import { describe, it, expect } from "vitest";
import { AgentIdentity } from "../src/identity.js";

describe("AgentIdentity", () => {
  it("generates a valid Ed25519 keypair + DID", async () => {
    const id = await AgentIdentity.generate();
    expect(id.did).toMatch(/^did:agora:[A-Za-z0-9_-]+$/);
    expect(id.privateKey.length).toBe(32);
    expect(id.publicKey.length).toBe(32);
  });

  it("derives a stable DID from a known key", async () => {
    const id1 = await AgentIdentity.generate();
    const secret = id1.exportSecret();
    const id2 = await AgentIdentity.fromSecret(secret);
    expect(id2.did).toBe(id1.did);
    expect(id2.publicKey).toEqual(id1.publicKey);
  });

  it("produces a W3C DID document with verificationMethod", async () => {
    const id = await AgentIdentity.generate();
    const doc = id.didDocument("https://example.com/hook");
    expect(doc.id).toBe(id.did);
    expect(doc.verificationMethod[0].publicKeyMultibase).toMatch(/^z/);
    expect(doc.service?.[0].serviceEndpoint).toBe("https://example.com/hook");
  });

  it("signs a message and produces a 64-byte signature", async () => {
    const id = await AgentIdentity.generate();
    const sig = await id.sign(new TextEncoder().encode("hello"));
    expect(sig.length).toBe(64);
  });
});
