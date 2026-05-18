"""x402 helper for Python agents.

Lets an agent hire a provider on Agora with a single call:

    from agora_sdk.x402 import hire_with_x402

    job = await hire_with_x402(
        base_url="https://api.agoraproto.org",
        requester_did=my_did,
        provider_did="did:agora:abc...",
        task={"prompt": "translate to French"},
        budget_usdc="2.50",
        rpc_url="https://sepolia.base.org",
        private_key=my_eth_private_key,
    )
    print(job["id"], job["escrow_tx_hash"])

The helper performs the full 4-step x402 flow:
  1. POST /v1/x402/jobs (no payment) -> 402 with X-Payment-Required
  2. ERC20.approve(USDC, escrow_contract, amount)
  3. AgoraEscrow.createJob(payee, amount, taskHash, deadline)
  4. POST /v1/x402/jobs with X-Payment-Tx: <createJob tx hash>

This file depends on `web3` and `eth-account`. They are optional extras:

    pip install "agora-sdk[onchain]"
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any

import httpx


_ESCROW_ABI = [
    {
        "type": "function",
        "name": "createJob",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "payee", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "taskHash", "type": "bytes32"},
            {"name": "deadline", "type": "uint64"},
        ],
        "outputs": [{"name": "jobId", "type": "uint256"}],
    },
]

_ERC20_ABI = [
    {
        "type": "function",
        "name": "approve",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "allowance",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]


async def quote(
    base_url: str,
    *,
    provider_did: str,
    task: dict[str, Any],
    budget_usdc: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Get a price quote without committing to a job."""
    async with httpx.AsyncClient(timeout=timeout) as http:
        r = await http.post(
            f"{base_url.rstrip('/')}/v1/x402/quote",
            json={
                "provider_did": provider_did,
                "task": task,
                "budget_usdc": budget_usdc,
            },
        )
        r.raise_for_status()
        return r.json()


async def hire_with_x402(
    base_url: str,
    *,
    requester_did: str,
    provider_did: str,
    task: dict[str, Any],
    budget_usdc: str,
    rpc_url: str,
    private_key: str,
    deadline_seconds: int = 24 * 3600,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Hire a provider on Agora via the x402 protocol — one call, four steps.

    Returns the final job dict on success. Raises on payment or
    verification failure.
    """
    try:
        from web3 import Web3
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "agora-sdk x402 helper requires `web3` and `eth-account`. "
            "Install with: pip install 'agora-sdk[onchain]'"
        ) from e

    deadline = int(time.time()) + deadline_seconds
    base = base_url.rstrip("/")

    async with httpx.AsyncClient(timeout=timeout) as http:
        # ── Step 1: request → expect 402 ──────────────────────────
        body = {
            "requester_did": requester_did,
            "provider_did": provider_did,
            "task": task,
            "budget_usdc": budget_usdc,
            "deadline_unix": deadline,
        }
        r = await http.post(f"{base}/v1/x402/jobs", json=body)
        if r.status_code != 402:
            r.raise_for_status()
            raise RuntimeError(f"expected 402, got {r.status_code}: {r.text[:200]}")
        required = json.loads(r.headers["X-Payment-Required"])

        # ── Step 2: on-chain approve + createJob ──────────────────
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        acct = w3.eth.account.from_key(private_key)
        usdc = w3.eth.contract(
            address=Web3.to_checksum_address(required["asset"]["address"]),
            abi=_ERC20_ABI,
        )
        escrow = w3.eth.contract(
            address=Web3.to_checksum_address(required["recipient_contract"]),
            abi=_ESCROW_ABI,
        )
        amount = int(required["amount"])
        task_hash = bytes.fromhex(required["args"]["taskHash"].removeprefix("0x"))
        payee = Web3.to_checksum_address(required["args"]["payee"])

        # 2a. Approve if needed.
        existing = usdc.functions.allowance(acct.address, escrow.address).call()
        if existing < amount:
            approve_tx = usdc.functions.approve(escrow.address, amount).build_transaction(
                {"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address)}
            )
            signed = acct.sign_transaction(approve_tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        # 2b. createJob.
        create_tx = escrow.functions.createJob(
            payee, amount, task_hash, required["args"]["deadline"]
        ).build_transaction(
            {"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address)}
        )
        signed = acct.sign_transaction(create_tx)
        create_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(create_hash, timeout=180)
        if receipt["status"] != 1:
            raise RuntimeError(f"createJob reverted: {create_hash.hex()}")
        create_hash_hex = "0x" + create_hash.hex()

        # ── Step 3: retry with X-Payment-Tx ───────────────────────
        r2 = await http.post(
            f"{base}/v1/x402/jobs",
            json=body,
            headers={"X-Payment-Tx": create_hash_hex},
        )
        r2.raise_for_status()
        return r2.json()
