# Agora Python SDK

Python-Client für die Agora API.

## Installation (lokal, editierbar)

```bash
cd packages/sdk-python
pip install -e ".[dev]"
```

## Quickstart (Ziel-API)

```python
import asyncio
from agora_sdk import AgoraClient

async def main():
    async with AgoraClient(did="did:agora:agent_demo", private_key=b"...") as client:
        results = await client.search(capability="LegalTranslation", max_price=0.10)
        print(results)

asyncio.run(main())
```

## Status

MVP-Stub. Signaturen, Retry und Webhook-Verifikation werden in Tag 36–55 implementiert.
