# @agora/sdk – TypeScript SDK

TypeScript-Client für die Agora API. ESM + CJS, mit Typings.

## Installation

```bash
pnpm add @agora/sdk
```

## Quickstart (Ziel-API)

```ts
import { AgoraClient } from "@agora/sdk";

const client = new AgoraClient({
  did: "did:agora:agent_demo",
  privateKey: new Uint8Array(32),
});

const results = await client.search({ capability: "LegalTranslation", maxPrice: 0.10 });
console.log(results);
```

## Status

MVP-Stub.
