"""Sprint 19 — POST /v1/agents/bootstrap.

The "one HTTP call. Your agent is on Agora." endpoint. The caller doesn't
need to know about Ed25519, DID-documents, multibase encoding, or EVM
wallets — the server generates everything and returns it ONCE in the
response. The caller must save the credentials immediately (they are
NOT persisted in plaintext anywhere on the server).

This dramatically lowers the onboarding cost for new agents. Before
Sprint 19 the dance was:

  1. pip install cryptography
  2. Generate Ed25519 keypair, encode public key as multibase (0xed01 + base58btc + 'z')
  3. Build a W3C DID document by hand
  4. Generate an EVM wallet with eth_account
  5. POST /v1/agents/register with the assembled body
  6. Manually fund the wallet with Sepolia ETH from a faucet

After Sprint 19 it's:

  POST /v1/agents/bootstrap
  { "name": "my-agent", "capabilities": ["Translation"], "pricing": {"base_price": "0.50"} }

  → 201 with did, ed25519_private_key_hex, evm_address, evm_private_key_hex,
    webhook_secret, all-in-one. Server has already funded the wallet with
    0.001 ETH from the deployer for gas.

This is the response to the third-party Claude UX-audit finding #4:
"Onboarding-Reibung ist größer als beworben."
"""

from __future__ import annotations

import base64
import os
from decimal import Decimal
from typing import Any

from eth_account import Account
from fastapi import APIRouter, Depends, HTTPException, Request, status
from nacl.signing import SigningKey
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import agents_repo
from ..db.base import get_session
from ..rate_limit import limiter

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# Request / response schemas
# ─────────────────────────────────────────────────────────────────────


class BootstrapRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255,
                      description="Human-readable agent name, e.g. 'EN-DE Translator'")
    description: str = Field(default="", max_length=2000)
    capabilities: list[str] = Field(
        default_factory=list,
        description="List of capability tags (free-form, e.g. ['Translation', 'Summarization'])",
    )
    pricing: dict[str, Any] = Field(
        default_factory=lambda: {"model": "per_request", "currency": "USDC", "base_price": "0.50"},
        description="Pricing object — defaults to per-request USDC at 0.50",
    )
    endpoint_url: str = Field(
        default="",
        description="Optional public HTTPS URL where Agora delivers webhook events. "
                    "Leave empty if the agent will poll /v1/jobs instead.",
    )
    fund_eth: bool = Field(
        default=True,
        description="Whether the server should fund the newly-generated EVM "
                    "wallet with 0.001 ETH from the deployer for gas. "
                    "Defaults to true — set false if you'll fund the wallet yourself.",
    )


class BootstrapResponse(BaseModel):
    did: str
    name: str
    trust_level: str
    ed25519_private_key_hex: str
    ed25519_public_key_multibase: str
    evm_address: str
    evm_private_key_hex: str
    webhook_secret: str
    funded_eth_amount: str
    funded_eth_tx: str | None
    funded_eth_error: str | None
    warning: str


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(data: bytes) -> bytes:
    """Inline base58btc encoder so we don't need an extra dependency."""
    n = int.from_bytes(data, "big")
    out = bytearray()
    while n > 0:
        n, r = divmod(n, 58)
        out.insert(0, _B58_ALPHABET[r])
    # Leading zero bytes are encoded as leading '1' characters.
    for b in data:
        if b == 0:
            out.insert(0, ord(b"1"))
        else:
            break
    return bytes(out)


def _ed25519_pubkey_multibase(pubkey_bytes: bytes) -> str:
    """Encode a 32-byte Ed25519 public key as W3C multibase string.

    Format: 'z' (base58btc multibase prefix) + base58(0xed01 + raw_pubkey).
    See https://w3c-ccg.github.io/multikey/ for the Ed25519Multikey spec.
    """
    payload = bytes([0xed, 0x01]) + pubkey_bytes
    return "z" + _b58encode(payload).decode("ascii")


def _generate_did_document(ed25519_pubkey: bytes, evm_address: str) -> tuple[str, dict[str, Any]]:
    """Build a minimal W3C-compliant DID document.

    Returns (did_string, did_document_dict).
    """
    # The DID is derived deterministically from the public key for stability.
    fingerprint = base64.urlsafe_b64encode(ed25519_pubkey[:16]).rstrip(b"=").decode("ascii")
    did = f"did:agora:bootstrap-{fingerprint}"
    pubkey_mb = _ed25519_pubkey_multibase(ed25519_pubkey)

    doc = {
        "@context": ["https://www.w3.org/ns/did/v1", "https://w3id.org/security/multikey/v1"],
        "id": did,
        "verificationMethod": [
            {
                "id": f"{did}#key-1",
                "type": "Ed25519VerificationKey2020",
                "controller": did,
                "publicKeyMultibase": pubkey_mb,
            },
            {
                "id": f"{did}#evm",
                "type": "EcdsaSecp256k1RecoveryMethod2020",
                "controller": did,
                "blockchainAccountId": f"eip155:84532:{evm_address}",
            },
        ],
        "authentication": [f"{did}#key-1"],
        "assertionMethod": [f"{did}#key-1"],
    }
    return did, doc


async def _fund_wallet_eth(target_address: str) -> tuple[str, str | None, str | None]:
    """Send 0.001 ETH from the deployer wallet to target_address.

    Returns (amount_sent_eth, tx_hash_or_none, error_or_none). When fund
    fails we surface the reason in the third return value so the caller
    can see why (e.g. permission, key not found, RPC error).
    """
    try:
        from web3 import Web3
    except ImportError as e:
        return ("0", None, f"web3 import failed: {e}")

    key_paths = [
        "/opt/agora/experiments/swarm/.deployer-key",
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..",
                     "experiments", "swarm", ".deployer-key"),
    ]
    deployer_key: str | None = None
    last_err = None
    for p in key_paths:
        try:
            if os.path.isfile(p):
                with open(p) as f:
                    deployer_key = f.read().strip()
                    break
            else:
                last_err = f"not a file: {p}"
        except PermissionError as e:
            last_err = f"permission denied on {p}: {e}"
        except Exception as e:
            last_err = f"read {p} failed: {e}"
    if not deployer_key:
        return ("0", None, last_err or "deployer key not found in any of the configured paths")
    if not deployer_key.startswith("0x"):
        deployer_key = "0x" + deployer_key

    try:
        w3 = Web3(Web3.HTTPProvider("https://sepolia.base.org", request_kwargs={"timeout": 15}))
        if not w3.is_connected():
            return ("0", None, "RPC not reachable")
        deployer = Account.from_key(deployer_key)
        nonce = w3.eth.get_transaction_count(deployer.address, "pending")
        amount_wei = int(0.001 * 10**18)
        gas_price = w3.eth.gas_price
        tx = {
            "to": Web3.to_checksum_address(target_address),
            "value": amount_wei,
            "gas": 21000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": 84532,
        }
        signed = deployer.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        return ("0.001", "0x" + h.hex(), None)
    except Exception as e:
        return ("0", None, f"on-chain send failed: {e}")


# ─────────────────────────────────────────────────────────────────────
# Diagnose endpoint (Sprint 19c) — surfaces the exact reason the
# server can or cannot fund a new wallet. Useful when bootstrap returns
# `funded_eth_amount: 0` and we don't yet know whether the cause is a
# permission issue on .deployer-key, an unreachable RPC, an empty
# deployer wallet, or something else.
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/diagnose",
    summary="Diagnose the auto-fund pipeline (no agent created)",
)
async def diagnose_fund_pipeline() -> dict[str, Any]:
    """Probe everything _fund_wallet_eth needs to succeed.

    No agent is created. Safe to call from anywhere — the response only
    exposes the deployer's PUBLIC address and balance, never the key.
    """
    out: dict[str, Any] = {
        "process_uid": os.getuid() if hasattr(os, "getuid") else None,
        "process_euid": os.geteuid() if hasattr(os, "geteuid") else None,
        "key_paths_tried": [],
        "key_readable": False,
        "key_readable_path": None,
        "key_read_error": None,
        "deployer_address": None,
        "rpc_url": "https://sepolia.base.org",
        "rpc_connected": False,
        "rpc_error": None,
        "deployer_balance_eth": None,
        "ready_to_fund": False,
    }

    key_paths = [
        "/opt/agora/experiments/swarm/.deployer-key",
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..",
                     "experiments", "swarm", ".deployer-key"),
    ]
    deployer_key: str | None = None
    last_err = None
    for p in key_paths:
        info: dict[str, Any] = {"path": p, "exists": False, "is_file": False, "stat": None, "read_error": None}
        try:
            info["exists"] = os.path.exists(p)
            info["is_file"] = os.path.isfile(p)
            if info["is_file"]:
                st = os.stat(p)
                info["stat"] = {"mode_octal": oct(st.st_mode & 0o777), "uid": st.st_uid, "gid": st.st_gid, "size": st.st_size}
                with open(p) as f:
                    deployer_key = f.read().strip()
        except PermissionError as e:
            info["read_error"] = f"PermissionError: {e}"
            last_err = info["read_error"]
        except Exception as e:
            info["read_error"] = f"{type(e).__name__}: {e}"
            last_err = info["read_error"]
        out["key_paths_tried"].append(info)
        if deployer_key:
            out["key_readable"] = True
            out["key_readable_path"] = p
            break
    if not deployer_key:
        out["key_read_error"] = last_err or "deployer key not found in any of the configured paths"
        return out

    try:
        if not deployer_key.startswith("0x"):
            deployer_key = "0x" + deployer_key
        out["deployer_address"] = Account.from_key(deployer_key).address
    except Exception as e:
        out["key_read_error"] = f"key invalid: {e}"
        return out

    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(out["rpc_url"], request_kwargs={"timeout": 10}))
        out["rpc_connected"] = bool(w3.is_connected())
        if out["rpc_connected"] and out["deployer_address"]:
            bal_wei = w3.eth.get_balance(out["deployer_address"])
            out["deployer_balance_eth"] = str(Decimal(bal_wei) / Decimal(10**18))
            out["ready_to_fund"] = Decimal(out["deployer_balance_eth"]) > Decimal("0.002")
    except Exception as e:
        out["rpc_error"] = f"{type(e).__name__}: {e}"

    return out


# ─────────────────────────────────────────────────────────────────────
# Route
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=BootstrapResponse,
    summary="Bootstrap a new agent — server generates keys + DID + funded wallet",
)
@limiter.limit("5/minute")
async def bootstrap_agent(
    request: Request,
    body: BootstrapRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Generate everything an agent needs to start trading on Agora in one call.

    The server:
      1. Generates an Ed25519 keypair (DID auth key)
      2. Generates an EVM keypair (escrow / payout wallet)
      3. Builds a W3C-compliant DID-document
      4. Registers the agent (trust = probation, stake = 0)
      5. Optionally funds the EVM wallet with 0.001 ETH from the deployer

    Returns ALL secrets exactly once. The caller MUST save them — the
    server doesn't store them in plaintext anywhere. If you lose them you
    cannot recover the agent's identity or wallet.
    """
    # 1. Ed25519 keypair
    signing = SigningKey.generate()
    ed_priv = bytes(signing).hex()
    ed_pub = bytes(signing.verify_key)
    ed_pub_mb = _ed25519_pubkey_multibase(ed_pub)

    # 2. EVM keypair
    evm_acc = Account.create()
    evm_address = evm_acc.address
    evm_priv = evm_acc.key.hex()
    if not evm_priv.startswith("0x"):
        evm_priv = "0x" + evm_priv

    # 3. DID document
    did, did_doc = _generate_did_document(ed_pub, evm_address)

    # 4. Persist to DB via existing repo
    try:
        agent, webhook_secret = await agents_repo.create(
            session,
            did=did,
            did_document=did_doc,
            name=body.name,
            description=body.description,
            owner_did=did,  # self-owned for bootstrap
            capabilities=[{"type": cap} for cap in body.capabilities],
            pricing=body.pricing,
            endpoint_url=body.endpoint_url,
            stake_eur=Decimal("0"),  # no stake for bootstrap; sponsor flow exists separately
            sponsor_did=None,
            sponsor_signature=None,
        )
        # Set the payout_wallet to the freshly-minted EVM address.
        agent.payout_wallet = evm_address
        await session.flush()
        await session.commit()
        await session.refresh(agent)
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"failed to register: {e}") from e

    # 5. Optionally fund wallet for gas
    funded_amt, funded_tx, fund_err = ("0", None, "fund_eth disabled by caller")
    if body.fund_eth:
        funded_amt, funded_tx, fund_err = await _fund_wallet_eth(evm_address)

    return {
        "did": did,
        "name": agent.name,
        "trust_level": agent.trust_level.value if hasattr(agent.trust_level, "value") else str(agent.trust_level),
        "ed25519_private_key_hex": ed_priv,
        "ed25519_public_key_multibase": ed_pub_mb,
        "evm_address": evm_address,
        "evm_private_key_hex": evm_priv,
        "webhook_secret": webhook_secret,
        "funded_eth_amount": funded_amt,
        "funded_eth_tx": funded_tx,
        "funded_eth_error": fund_err,
        "warning": (
            "Save these credentials NOW. The server does NOT store the private "
            "keys in plaintext. If you lose them, you cannot recover the agent's "
            "identity or wallet."
        ),
    }
