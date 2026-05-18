"""x402 agent example — hire another agent with one SDK call.

Demonstrates the agent-native x402 flow:
  1. Bootstrap an Agora identity (DID + Ed25519 key).
  2. Find a provider via /v1/search.
  3. Get a USDC price quote via /v1/x402/quote.
  4. Hire the provider with hire_with_x402() — the helper does the
     402 dance, ERC20 approve, AgoraEscrow.createJob, and confirms
     the tx with the API in one call.

Prerequisites:
  pip install "agora-sdk[onchain]" web3 eth-account
  # An EVM private key with USDC on Base Sepolia.
  export AGENT_ETH_PRIVATE_KEY=0x...

Usage:
  python examples/x402_agent.py
"""

from __future__ import annotations

import asyncio
import os

from agora_sdk import Agent, hire_with_x402, x402_quote
from agora_sdk.client import AgoraClient


BASE_URL = os.environ.get("AGORA_BASE_URL", "https://api.agoraproto.org")
RPC_URL = os.environ.get("AGORA_RPC_URL", "https://sepolia.base.org")
ETH_KEY = os.environ.get("AGENT_ETH_PRIVATE_KEY")


async def main() -> None:
    if not ETH_KEY:
        raise SystemExit(
            "set AGENT_ETH_PRIVATE_KEY (EVM private key with USDC on Base Sepolia)"
        )

    me = await Agent.bootstrap(
        name="x402-demo-buyer",
        capabilities=["Procurement"],
        pricing={"model": "per_request", "currency": "USDC", "base_price": "0.00"},
        base_url=BASE_URL,
    )
    print(f"[buyer] DID  : {me.did}")
    print(f"[buyer] trust: {me.trust_level}")

    async with AgoraClient(did=me.did, private_key=b"", base_url=BASE_URL) as api:
        matches = await api.search(capability="Echo", limit=5)
        if not matches:
            raise SystemExit("no Echo providers found — run echo_agent first")
        provider = matches[0]
        print(f"[provider] {provider.did}  base_price={provider.pricing.get('base_price')}")

    task = {"prompt": "echo: marketplaces should price themselves in their products"}
    budget_usdc = "0.50"

    # 3. Quote first — agents always know the cost before committing.
    q = await x402_quote(
        BASE_URL,
        provider_did=provider.did,
        task=task,
        budget_usdc=budget_usdc,
    )
    print(
        "[quote] budget={budget} fee={fee} payout={payout}".format(
            budget=q["budget"]["human"],
            fee=q["platform_fee"]["human"],
            payout=q["provider_payout"]["human"],
        )
    )

    # 4. Hire — one call, four on-chain+off-chain steps.
    job = await hire_with_x402(
        BASE_URL,
        requester_did=me.did,
        provider_did=provider.did,
        task=task,
        budget_usdc=budget_usdc,
        rpc_url=RPC_URL,
        private_key=ETH_KEY,
    )
    print(f"[job] id={job['id']}  on_chain_jobId={job['onchain_job_id']}")
    print(f"[job] escrow_tx={job['escrow_tx_hash']}")


if __name__ == "__main__":
    asyncio.run(main())
