"""AgoraEscrow client (web3.py wrapper).

Settlement model
================
- `createJob(payee, amount, taskHash, deadline)` -> uint256 jobId
- `submitResult(jobId, resultHash)` (called by payee/provider)
- `approveAndPay(jobId)` (called by payer/requester after they accept)
- `dispute(jobId, reason)` / `refund(jobId)`

The backend uses a single platform-owned settler key
(`settings.agora_settler_private_key`) to broadcast on behalf of agents.
Agents that hold their own keys can call the contract directly via the
SDK; this client exists for the "I trust Agora to relay" path and for
x402-style synchronous payments.

The Solidity ABI here is the minimal subset we actually call; if the
contract is extended, add the function/event here too.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from typing import Any

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from web3.types import TxReceipt

from ..config import get_settings

log = logging.getLogger(__name__)


# ABI subset for AgoraEscrow.sol
_ESCROW_ABI: list[dict[str, Any]] = [
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
    {
        "type": "function",
        "name": "submitResult",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "jobId", "type": "uint256"},
            {"name": "resultHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "approveAndPay",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "jobId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "dispute",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "jobId", "type": "uint256"},
            {"name": "reason", "type": "string"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "refund",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "jobId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "jobs",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "uint256"}],
        "outputs": [
            {"name": "payer", "type": "address"},
            {"name": "payee", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "taskHash", "type": "bytes32"},
            {"name": "resultHash", "type": "bytes32"},
            {"name": "deadline", "type": "uint64"},
            {"name": "status", "type": "uint8"},
        ],
    },
    {
        "type": "function",
        "name": "computeFee",
        "stateMutability": "view",
        "inputs": [{"name": "amount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "event",
        "name": "JobCreated",
        "inputs": [
            {"name": "jobId", "type": "uint256", "indexed": True},
            {"name": "payer", "type": "address", "indexed": True},
            {"name": "payee", "type": "address", "indexed": True},
            {"name": "amount", "type": "uint256", "indexed": False},
            {"name": "taskHash", "type": "bytes32", "indexed": False},
            {"name": "deadline", "type": "uint64", "indexed": False},
        ],
        "anonymous": False,
    },
    {
        "type": "event",
        "name": "JobApproved",
        "inputs": [
            {"name": "jobId", "type": "uint256", "indexed": True},
            {"name": "fee", "type": "uint256", "indexed": False},
            {"name": "insuranceCut", "type": "uint256", "indexed": False},
        ],
        "anonymous": False,
    },
    {
        "type": "event",
        "name": "ResultSubmitted",
        "inputs": [
            {"name": "jobId", "type": "uint256", "indexed": True},
            {"name": "resultHash", "type": "bytes32", "indexed": False},
        ],
        "anonymous": False,
    },
    {
        "type": "event",
        "name": "JobDisputed",
        "inputs": [
            {"name": "jobId", "type": "uint256", "indexed": True},
            {"name": "reason", "type": "string", "indexed": False},
        ],
        "anonymous": False,
    },
    {
        "type": "event",
        "name": "JobRefunded",
        "inputs": [
            {"name": "jobId", "type": "uint256", "indexed": True},
        ],
        "anonymous": False,
    },
]

# Minimal ERC20 ABI for approve/balanceOf checks against USDC.
_ERC20_ABI: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
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
]


# Sprint 35a: ABI superset for AgoraEscrowV2 (contracts/src/AgoraEscrowV2.sol).
#
# V2 is committed but not yet deployed; this constant lets us point the
# AgoraEscrowClient at a V2 contract address (via a future config switch)
# without an emergency hotfix. Key differences vs _ESCROW_ABI above:
#
#   - splits v1 `refund()` into permissionless `refundExpired()` and
#     owner-only `resolveDispute(jobId, payeeAmount, payerAmount)`
#   - adds `previewFee(amount)` (replaces v1's `computeFee` for callers
#     who want current-parameter quoting; v2 also exposes the snapshot
#     fee in the Job struct)
#   - new event `JobResolved` with (payeeAmount, payerAmount, fee,
#     insuranceCut) tuple
#   - `JobDisputed` adds an indexed `raisedBy` topic
#   - `JobRefunded` adds (to, amount) data
#   - jobs(jobId) view returns the snapshot fee params in addition to the
#     v1 fields
#
# To use: set `settings.escrow_abi_version = "v2"` (planned config), then
# AgoraEscrowClient picks _ESCROW_V2_ABI in its constructor. Until V2 is
# deployed, this constant is unused but committed so the migration is a
# pure config flip, not a code change.
_ESCROW_V2_ABI: list[dict[str, Any]] = [
    {"type": "function", "name": "createJob", "stateMutability": "nonpayable",
     "inputs": [{"name": "payee", "type": "address"}, {"name": "amount", "type": "uint256"},
                {"name": "taskHash", "type": "bytes32"}, {"name": "deadline", "type": "uint64"}],
     "outputs": [{"name": "jobId", "type": "uint256"}]},
    {"type": "function", "name": "submitResult", "stateMutability": "nonpayable",
     "inputs": [{"name": "jobId", "type": "uint256"}, {"name": "resultHash", "type": "bytes32"}],
     "outputs": []},
    {"type": "function", "name": "approveAndPay", "stateMutability": "nonpayable",
     "inputs": [{"name": "jobId", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "dispute", "stateMutability": "nonpayable",
     "inputs": [{"name": "jobId", "type": "uint256"}, {"name": "reason", "type": "string"}],
     "outputs": []},
    {"type": "function", "name": "refundExpired", "stateMutability": "nonpayable",
     "inputs": [{"name": "jobId", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "resolveDispute", "stateMutability": "nonpayable",
     "inputs": [{"name": "jobId", "type": "uint256"},
                {"name": "payeeAmount", "type": "uint256"},
                {"name": "payerAmount", "type": "uint256"}],
     "outputs": []},
    {"type": "function", "name": "previewFee", "stateMutability": "view",
     "inputs": [{"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "jobs", "stateMutability": "view",
     "inputs": [{"name": "", "type": "uint256"}],
     "outputs": [
         {"name": "payer", "type": "address"},
         {"name": "payee", "type": "address"},
         {"name": "amount", "type": "uint256"},
         {"name": "taskHash", "type": "bytes32"},
         {"name": "resultHash", "type": "bytes32"},
         {"name": "deadline", "type": "uint64"},
         {"name": "status", "type": "uint8"},
         {"name": "snapshotFeeBps", "type": "uint16"},
         {"name": "snapshotMinFee", "type": "uint256"},
         {"name": "snapshotMaxFee", "type": "uint256"},
         {"name": "snapshotInsuranceShareBps", "type": "uint16"},
     ]},
    {"type": "event", "name": "JobCreated", "anonymous": False,
     "inputs": [
         {"name": "jobId", "type": "uint256", "indexed": True},
         {"name": "payer", "type": "address", "indexed": True},
         {"name": "payee", "type": "address", "indexed": True},
         {"name": "amount", "type": "uint256", "indexed": False},
         {"name": "taskHash", "type": "bytes32", "indexed": False},
         {"name": "deadline", "type": "uint64", "indexed": False},
     ]},
    {"type": "event", "name": "JobApproved", "anonymous": False,
     "inputs": [
         {"name": "jobId", "type": "uint256", "indexed": True},
         {"name": "fee", "type": "uint256", "indexed": False},
         {"name": "insuranceCut", "type": "uint256", "indexed": False},
     ]},
    {"type": "event", "name": "ResultSubmitted", "anonymous": False,
     "inputs": [
         {"name": "jobId", "type": "uint256", "indexed": True},
         {"name": "resultHash", "type": "bytes32", "indexed": False},
     ]},
    {"type": "event", "name": "JobDisputed", "anonymous": False,
     "inputs": [
         {"name": "jobId", "type": "uint256", "indexed": True},
         {"name": "raisedBy", "type": "address", "indexed": True},
         {"name": "reason", "type": "string", "indexed": False},
     ]},
    {"type": "event", "name": "JobRefunded", "anonymous": False,
     "inputs": [
         {"name": "jobId", "type": "uint256", "indexed": True},
         {"name": "to", "type": "address", "indexed": True},
         {"name": "amount", "type": "uint256", "indexed": False},
     ]},
    {"type": "event", "name": "JobResolved", "anonymous": False,
     "inputs": [
         {"name": "jobId", "type": "uint256", "indexed": True},
         {"name": "payeeAmount", "type": "uint256", "indexed": False},
         {"name": "payerAmount", "type": "uint256", "indexed": False},
         {"name": "fee", "type": "uint256", "indexed": False},
         {"name": "insuranceCut", "type": "uint256", "indexed": False},
     ]},
]



@dataclass(frozen=True)
class OnchainJob:
    """Read-back of AgoraEscrow.jobs(jobId)."""

    payer: str
    payee: str
    amount: int  # smallest USDC unit (6 decimals)
    task_hash: bytes
    result_hash: bytes
    deadline: int
    status: int  # JobStatus enum (0..5)


class AgoraEscrowClient:
    """Synchronous web3 calls wrapped in `asyncio.to_thread`.

    web3.py is sync-only; we offload to a thread so the FastAPI event
    loop is never blocked by an RPC roundtrip (~200-800ms on Base).
    """

    def __init__(
        self,
        rpc_url: str,
        escrow_address: str,
        usdc_address: str,
        settler_pk: str,
        usdc_decimals: int = 6,
    ) -> None:
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        # Base is an OP-stack chain; extra-data field needs POA middleware.
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        self.escrow = self.w3.eth.contract(
            address=Web3.to_checksum_address(escrow_address),
            abi=_ESCROW_ABI,
        )
        self.usdc = self.w3.eth.contract(
            address=Web3.to_checksum_address(usdc_address),
            abi=_ERC20_ABI,
        )
        self.settler = self.w3.eth.account.from_key(settler_pk) if settler_pk else None
        self.usdc_decimals = usdc_decimals

    # ── Reads ──────────────────────────────────────────────────────

    async def get_job(self, job_id: int) -> OnchainJob:
        def _read() -> OnchainJob:
            payer, payee, amount, task_hash, result_hash, deadline, status = (
                self.escrow.functions.jobs(job_id).call()
            )
            return OnchainJob(
                payer=payer,
                payee=payee,
                amount=int(amount),
                task_hash=task_hash,
                result_hash=result_hash,
                deadline=int(deadline),
                status=int(status),
            )

        return await asyncio.to_thread(_read)

    async def compute_fee(self, amount: int) -> int:
        def _read() -> int:
            return int(self.escrow.functions.computeFee(amount).call())

        return await asyncio.to_thread(_read)

    async def usdc_balance(self, address: str) -> int:
        def _read() -> int:
            return int(self.usdc.functions.balanceOf(Web3.to_checksum_address(address)).call())

        return await asyncio.to_thread(_read)

    # ── Writes (settler-broadcast) ─────────────────────────────────

    async def approve_and_pay(self, job_id: int) -> str:
        """Release escrow to payee. Returns tx_hash hex string.

        Note: the settler can only call approveAndPay if it is the
        original payer (Solidity guard `NotPayer`). For x402 flows where
        the requester is human/agent code rather than Agora, the
        requester must call this themselves via the SDK.
        """
        return await self._send_tx(
            self.escrow.functions.approveAndPay(job_id),
            tag="approveAndPay",
        )

    async def refund(self, job_id: int) -> str:
        return await self._send_tx(
            self.escrow.functions.refund(job_id),
            tag="refund",
        )

    async def settler_create_job(
        self,
        payee: str,
        amount: int,
        task_hash: bytes,
        deadline: int,
    ) -> tuple[str, int]:
        """Create a job on-chain from the settler wallet.

        Used by x402 endpoint when the *agent* paid USDC to the settler
        and Agora relays it into escrow. Returns (tx_hash, on_chain_jobId).
        """
        tx_hash = await self._send_tx(
            self.escrow.functions.createJob(
                Web3.to_checksum_address(payee),
                amount,
                task_hash,
                deadline,
            ),
            tag="createJob",
        )
        # Parse JobCreated log to recover the contract-side jobId.
        receipt = await asyncio.to_thread(
            self.w3.eth.wait_for_transaction_receipt, tx_hash, timeout=60
        )
        return tx_hash, self._extract_job_id(receipt)

    # ── Internals ──────────────────────────────────────────────────

    async def _send_tx(self, fn: Any, *, tag: str) -> str:
        if self.settler is None:
            raise RuntimeError(
                "agora_settler_private_key not configured; cannot broadcast tx"
            )

        def _build_and_send() -> str:
            nonce = self.w3.eth.get_transaction_count(self.settler.address)
            tx = fn.build_transaction(
                {
                    "from": self.settler.address,
                    "nonce": nonce,
                    "gas": 500_000,
                    "maxFeePerGas": self.w3.to_wei("0.1", "gwei"),
                    "maxPriorityFeePerGas": self.w3.to_wei("0.01", "gwei"),
                    "chainId": self.w3.eth.chain_id,
                }
            )
            signed = self.settler.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            log.info("chain.%s broadcast tx=%s", tag, tx_hash.hex())
            return "0x" + tx_hash.hex()

        return await asyncio.to_thread(_build_and_send)

    def _extract_job_id(self, receipt: TxReceipt) -> int:
        evt = self.escrow.events.JobCreated()
        for log_entry in receipt["logs"]:
            try:
                parsed = evt.process_log(log_entry)
                return int(parsed["args"]["jobId"])
            except Exception:  # log may be from another contract
                continue
        raise RuntimeError("JobCreated event not found in receipt")

    # ── Helpers ────────────────────────────────────────────────────

    def to_smallest_unit(self, amount: Decimal) -> int:
        """Convert a USDC amount in human units to smallest unit (6 decimals)."""
        return int((amount * (10 ** self.usdc_decimals)).to_integral_value())

    def from_smallest_unit(self, amount: int) -> Decimal:
        return Decimal(amount) / Decimal(10 ** self.usdc_decimals)


@lru_cache(maxsize=1)
def get_escrow_client() -> AgoraEscrowClient | None:
    """Return a singleton client, or None if on-chain mode is disabled."""
    s = get_settings()
    if not s.enable_onchain_payments:
        return None
    if not (s.rpc_url and s.escrow_contract_address and s.usdc_contract_address):
        log.warning(
            "enable_onchain_payments=true but rpc_url/escrow/usdc not fully set"
        )
        return None
    return AgoraEscrowClient(
        rpc_url=s.rpc_url,
        escrow_address=s.escrow_contract_address,
        usdc_address=s.usdc_contract_address,
        settler_pk=s.agora_settler_private_key,
        usdc_decimals=s.usdc_decimals,
    )
