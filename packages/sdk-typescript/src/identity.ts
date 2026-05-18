/**
 * Agora agent identity: Ed25519 keypair + derived DID.
 *
 * Mirrors the Python SDK's AgentIdentity class.
 */

import * as ed25519 from "@noble/ed25519";
import { sha256 } from "@noble/hashes/sha256";

/** URL-safe base64 without padding, matching Python's urlsafe_b64encode().rstrip("="). */
function bytesToUrlsafeB64(bytes: Uint8Array): string {
  let b64 = btoa(String.fromCharCode(...bytes));
  b64 = b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return b64;
}

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function bytesToB64(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes));
}

/** Minimal base58 (Bitcoin alphabet) used for multibase public-key encoding. */
function b58encode(data: Uint8Array): string {
  const ALPHA = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  let n = 0n;
  for (const b of data) n = (n << 8n) + BigInt(b);
  let out = "";
  while (n > 0n) {
    const r = Number(n % 58n);
    n /= 58n;
    out = ALPHA[r] + out;
  }
  for (const b of data) {
    if (b === 0) out = "1" + out;
    else break;
  }
  return out || "1";
}

export interface DidDocumentService {
  id: string;
  type: string;
  serviceEndpoint: string;
}

export interface DidDocument {
  "@context": string[];
  id: string;
  verificationMethod: Array<{
    id: string;
    type: string;
    controller: string;
    publicKeyMultibase: string;
  }>;
  service?: DidDocumentService[];
}

export class AgentIdentity {
  constructor(
    public readonly did: string,
    public readonly privateKey: Uint8Array, // 32 bytes Ed25519 seed
    public readonly publicKey: Uint8Array, // 32 bytes Ed25519 public
  ) {}

  /** Generate a new random identity. */
  static async generate(): Promise<AgentIdentity> {
    const priv = ed25519.utils.randomPrivateKey();
    const pub = await ed25519.getPublicKeyAsync(priv);
    return new AgentIdentity(deriveDid(pub), priv, pub);
  }

  /** Restore from base64-encoded private key. */
  static async fromSecret(b64Secret: string): Promise<AgentIdentity> {
    const priv = b64ToBytes(b64Secret);
    const pub = await ed25519.getPublicKeyAsync(priv);
    return new AgentIdentity(deriveDid(pub), priv, pub);
  }

  /** Multibase-encoded public key (0xed01 + base58btc) per W3C DID spec. */
  publicKeyMultibase(): string {
    const prefix = new Uint8Array([0xed, 0x01]);
    const buf = new Uint8Array(prefix.length + this.publicKey.length);
    buf.set(prefix, 0);
    buf.set(this.publicKey, prefix.length);
    return "z" + b58encode(buf);
  }

  /** Base64-encoded private key for local storage. NEVER share. */
  exportSecret(): string {
    return bytesToB64(this.privateKey);
  }

  /** Sign an arbitrary message. */
  async sign(message: Uint8Array): Promise<Uint8Array> {
    return await ed25519.signAsync(message, this.privateKey);
  }

  /** Build the DID document for registration. */
  didDocument(endpointUrl?: string): DidDocument {
    const doc: DidDocument = {
      "@context": ["https://www.w3.org/ns/did/v1"],
      id: this.did,
      verificationMethod: [
        {
          id: `${this.did}#key-1`,
          type: "Ed25519VerificationKey2020",
          controller: this.did,
          publicKeyMultibase: this.publicKeyMultibase(),
        },
      ],
    };
    if (endpointUrl) {
      doc.service = [
        {
          id: `${this.did}#agora`,
          type: "AgoraAgentEndpoint",
          serviceEndpoint: endpointUrl,
        },
      ];
    }
    return doc;
  }
}

function deriveDid(publicKey: Uint8Array): string {
  // did:agora:<urlsafe_b64( sha256(pubkey)[:16] )>
  const hash = sha256(publicKey).slice(0, 16);
  return `did:agora:${bytesToUrlsafeB64(hash)}`;
}
