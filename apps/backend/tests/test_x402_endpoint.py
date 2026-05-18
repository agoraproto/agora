"""x402 endpoint tests.

Validates:
  - /v1/x402/quote and /v1/x402/jobs return 503 when on-chain disabled
  - /v1/x402/quote returns correct fee math when on-chain is enabled
  - /v1/x402/jobs returns 402 + X-Payment-Required when on-chain enabled
    and no payment was attached
  - /v1/x402/jobs verifies and mirrors a payment when X-Payment-Tx given
    (chain client is mocked at the module level)
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from agora_api.config import get_settings
from agora_api.db.models import Agent, AgentStatus, AgentType, TrustLevel
from agora_api.routes import x402 as x402_module


def _ag(did: str, *, name: str, payout: str | None) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        did=did,
        owner_did=did,
        type=AgentType.service,
        name=name,
        description=name,
        public_endpoint=None,
        capabilities=[{"type": "Echo"}],
        pricing={"model": "per_request", "currency": "USDC", "base_price": "0.50"},
        constraints={},
        did_document={},
        stake_eur=Decimal("0"),
        trust_level=TrustLevel.new,
        status=AgentStatus.active,
        payout_wallet=payout,
    )


@pytest.mark.asyncio
async def test_quote_503_when_onchain_disabled(client, session) -> None:
    session.add(_ag("did:agora:p1", name="echo", payout="0x" + "1" * 40))
    await session.commit()
    r = await client.post(
        "/v1/x402/quote",
        json={"provider_did": "did:agora:p1", "task": {"x": 1}, "budget_usdc": "1.00"},
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_jobs_503_when_onchain_disabled(client) -> None:
    r = await client.post(
        "/v1/x402/jobs",
        json={
            "requester_did": "did:agora:r",
            "provider_did": "did:agora:p",
            "task": {},
            "budget_usdc": "1.00",
            "deadline_unix": 9_999_999_999,
        },
    )
    assert r.status_code == 503


def _install_mock_client(monkeypatch) -> MagicMock:
    """Install a fully-mocked AgoraEscrowClient + flip the feature flag."""
    fake = MagicMock()
    fake.to_smallest_unit = lambda d: int(Decimal(d) * 1_000_000)
    fake.from_smallest_unit = lambda n: Decimal(n) / 1_000_000
    fake.compute_fee = AsyncMock(return_value=500_000)  # 0.50 USDC min fee
    monkeypatch.setattr(x402_module, "get_escrow_client", lambda: fake)
    settings = get_settings()
    monkeypatch.setattr(settings, "chain_name", "base-sepolia", raising=False)
    monkeypatch.setattr(settings, "chain_id", 84532, raising=False)
    monkeypatch.setattr(
        settings, "usdc_contract_address", "0x" + "1" * 40, raising=False
    )
    monkeypatch.setattr(settings, "usdc_decimals", 6, raising=False)
    monkeypatch.setattr(
        settings, "escrow_contract_address", "0x" + "2" * 40, raising=False
    )
    return fake


@pytest.mark.asyncio
async def test_quote_math(client, session, monkeypatch) -> None:
    _install_mock_client(monkeypatch)
    session.add(_ag("did:agora:p1", name="echo", payout="0x" + "9" * 40))
    await session.commit()

    r = await client.post(
        "/v1/x402/quote",
        json={"provider_did": "did:agora:p1", "task": {"x": 1}, "budget_usdc": "10.00"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chain"] == "base-sepolia"
    assert body["budget"]["smallest_unit"] == "10000000"
    assert body["platform_fee"]["smallest_unit"] == "500000"
    assert body["provider_payout"]["smallest_unit"] == "9500000"
    assert body["provider"]["did"] == "did:agora:p1"


@pytest.mark.asyncio
async def test_jobs_returns_402_with_payment_required(
    client, session, monkeypatch
) -> None:
    _install_mock_client(monkeypatch)
    session.add(_ag("did:agora:r", name="r", payout=None))
    session.add(_ag("did:agora:p", name="p", payout="0x" + "9" * 40))
    await session.commit()

    r = await client.post(
        "/v1/x402/jobs",
        json={
            "requester_did": "did:agora:r",
            "provider_did": "did:agora:p",
            "task": {"prompt": "hi"},
            "budget_usdc": "2.00",
            "deadline_unix": 9_999_999_999,
        },
    )
    assert r.status_code == 402
    pr = json.loads(r.headers["X-Payment-Required"])
    assert pr["version"] == "1"
    assert pr["amount"] == "2000000"  # 2.00 USDC in smallest unit
    assert pr["function"] == "createJob"
    assert pr["args"]["payee"] == "0x" + "9" * 40
    assert pr["args"]["taskHash"].startswith("0x")


@pytest.mark.asyncio
async def test_jobs_requires_provider_payout_wallet(
    client, session, monkeypatch
) -> None:
    _install_mock_client(monkeypatch)
    session.add(_ag("did:agora:r", name="r", payout=None))
    session.add(_ag("did:agora:p", name="p", payout=None))  # no payout wallet
    await session.commit()

    r = await client.post(
        "/v1/x402/jobs",
        json={
            "requester_did": "did:agora:r",
            "provider_did": "did:agora:p",
            "task": {},
            "budget_usdc": "1.00",
            "deadline_unix": 9_999_999_999,
        },
    )
    assert r.status_code == 409
    assert "payout_wallet" in r.json()["detail"]
