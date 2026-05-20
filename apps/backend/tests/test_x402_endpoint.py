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
async def test_quote_503_when_onchain_disabled(client, session, monkeypatch) -> None:
    # Explicit override — in production the .env enables on-chain, so we
    # must shadow `get_escrow_client` to return None here. This is the
    # surface contract the test asserts: "when no escrow client is
    # available, the endpoint short-circuits with 503".
    monkeypatch.setattr(x402_module, "get_escrow_client", lambda: None)
    session.add(_ag("did:agora:p1", name="echo", payout="0x" + "1" * 40))
    await session.commit()
    r = await client.post(
        "/v1/x402/quote",
        json={"provider_did": "did:agora:p1", "task": {"x": 1}, "budget_usdc": "1.00"},
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_jobs_503_when_onchain_disabled(client, monkeypatch) -> None:
    monkeypatch.setattr(x402_module, "get_escrow_client", lambda: None)
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


# ═════════════════════════════════════════════════════════════════════
# Provider-side result + requester-side approve + refund  (Sprint 9f)
# ═════════════════════════════════════════════════════════════════════


from agora_api.db.models import Job, JobStatus  # noqa: E402


def _onchain_job(
    requester: Agent,
    provider: Agent,
    *,
    status: JobStatus = JobStatus.offered,
    onchain_id: int = 7,
    price: str = "1.000000",
) -> Job:
    """Helper: build a Job in the DB the way create_x402_job would have."""
    return Job(
        id=uuid.uuid4(),
        requester_agent_id=requester.id,
        provider_agent_id=provider.id,
        task_spec={"text": "demo task"},
        status=status,
        price_amount=Decimal(price),
        price_currency="USDC",
        escrow_tx_hash="0x" + "a" * 64,
        onchain_job_id=Decimal(onchain_id),
        settlement_mode="onchain",
        chain="base-sepolia",
    )


def _patch_event(monkeypatch, expected_event_args: dict) -> None:
    """Make `_find_event` return a fake parsed-log dict.

    Avoids having to construct realistic web3 log bytes; the tests can
    just say "pretend the receipt contained this event".
    """
    monkeypatch.setattr(
        x402_module,
        "_find_event",
        lambda receipt, ev: {"args": expected_event_args, "event": "stubbed"},
    )


def _patch_receipt_ok(fake_client: MagicMock) -> None:
    """Make get_transaction_receipt return a successful receipt."""
    fake_client.w3 = MagicMock()
    fake_client.w3.eth = MagicMock()
    fake_client.w3.eth.get_transaction_receipt = MagicMock(
        return_value={"status": 1, "logs": []}
    )
    # Event factories must exist as attributes on .escrow.events even
    # though _find_event is stubbed, because route code reads them by name.
    fake_client.escrow = MagicMock()
    fake_client.escrow.events = MagicMock()


# ── /jobs/{id}/result ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_result_returns_402_with_submit_result_args(
    client, session, monkeypatch
) -> None:
    _install_mock_client(monkeypatch)
    requester = _ag("did:agora:r", name="r", payout=None)
    provider = _ag("did:agora:p", name="p", payout="0x" + "9" * 40)
    session.add_all([requester, provider])
    await session.flush()
    job = _onchain_job(requester, provider, onchain_id=42)
    session.add(job)
    await session.commit()

    r = await client.post(
        f"/v1/x402/jobs/{job.id}/result",
        json={"result": {"echo": "hello"}},
    )
    assert r.status_code == 402, r.text
    pr = json.loads(r.headers["X-Payment-Required"])
    assert pr["function"] == "submitResult"
    assert pr["args"]["jobId"] == "42"
    assert pr["args"]["resultHash"].startswith("0x")
    assert pr["recipient_contract"] == "0x" + "2" * 40


@pytest.mark.asyncio
async def test_result_rejects_offchain_job(client, session, monkeypatch) -> None:
    _install_mock_client(monkeypatch)
    requester = _ag("did:agora:r", name="r", payout=None)
    provider = _ag("did:agora:p", name="p", payout="0x" + "9" * 40)
    session.add_all([requester, provider])
    await session.flush()
    job = _onchain_job(requester, provider)
    job.settlement_mode = "offchain"
    session.add(job)
    await session.commit()

    r = await client.post(f"/v1/x402/jobs/{job.id}/result", json={"result": {}})
    assert r.status_code == 409
    assert "not on-chain" in r.json()["detail"]


@pytest.mark.asyncio
async def test_result_rejects_wrong_status(client, session, monkeypatch) -> None:
    _install_mock_client(monkeypatch)
    requester = _ag("did:agora:r", name="r", payout=None)
    provider = _ag("did:agora:p", name="p", payout="0x" + "9" * 40)
    session.add_all([requester, provider])
    await session.flush()
    job = _onchain_job(requester, provider, status=JobStatus.completed)
    session.add(job)
    await session.commit()

    r = await client.post(f"/v1/x402/jobs/{job.id}/result", json={"result": {}})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_result_succeeds_with_valid_tx(client, session, monkeypatch) -> None:
    fake = _install_mock_client(monkeypatch)
    _patch_receipt_ok(fake)
    requester = _ag("did:agora:r", name="r", payout=None)
    provider = _ag("did:agora:p", name="p", payout="0x" + "9" * 40)
    session.add_all([requester, provider])
    await session.flush()
    job = _onchain_job(requester, provider, onchain_id=42)
    session.add(job)
    await session.commit()

    # Compute the resultHash the server would expect.
    result_payload = {"echo": "hello"}
    expected_hash = x402_module._result_hash(result_payload)

    _patch_event(monkeypatch, {"jobId": 42, "resultHash": expected_hash})

    r = await client.post(
        f"/v1/x402/jobs/{job.id}/result",
        json={"result": result_payload},
        headers={"X-Payment-Tx": "0x" + "b" * 64},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "submitted"
    assert body["settlement_mode"] == "onchain"
    assert body["onchain_job_id"] == "42"


@pytest.mark.asyncio
async def test_result_rejects_wrong_result_hash(client, session, monkeypatch) -> None:
    fake = _install_mock_client(monkeypatch)
    _patch_receipt_ok(fake)
    requester = _ag("did:agora:r", name="r", payout=None)
    provider = _ag("did:agora:p", name="p", payout="0x" + "9" * 40)
    session.add_all([requester, provider])
    await session.flush()
    job = _onchain_job(requester, provider, onchain_id=42)
    session.add(job)
    await session.commit()

    # Event says some other hash than what the server will compute.
    _patch_event(monkeypatch, {"jobId": 42, "resultHash": b"\x00" * 32})

    r = await client.post(
        f"/v1/x402/jobs/{job.id}/result",
        json={"result": {"echo": "hello"}},
        headers={"X-Payment-Tx": "0x" + "b" * 64},
    )
    assert r.status_code == 402
    assert "resultHash mismatch" in r.json()["detail"]


# ── /jobs/{id}/approve ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_returns_402_with_args(client, session, monkeypatch) -> None:
    _install_mock_client(monkeypatch)
    requester = _ag("did:agora:r", name="r", payout=None)
    provider = _ag("did:agora:p", name="p", payout="0x" + "9" * 40)
    session.add_all([requester, provider])
    await session.flush()
    job = _onchain_job(requester, provider, status=JobStatus.submitted, onchain_id=42)
    session.add(job)
    await session.commit()

    r = await client.post(f"/v1/x402/jobs/{job.id}/approve", json={})
    assert r.status_code == 402, r.text
    pr = json.loads(r.headers["X-Payment-Required"])
    assert pr["function"] == "approveAndPay"
    assert pr["args"]["jobId"] == "42"


@pytest.mark.asyncio
async def test_approve_succeeds_with_valid_tx(client, session, monkeypatch) -> None:
    fake = _install_mock_client(monkeypatch)
    _patch_receipt_ok(fake)
    requester = _ag("did:agora:r", name="r", payout=None)
    provider = _ag("did:agora:p", name="p", payout="0x" + "9" * 40)
    session.add_all([requester, provider])
    await session.flush()
    job = _onchain_job(requester, provider, status=JobStatus.submitted, onchain_id=42)
    session.add(job)
    await session.commit()

    _patch_event(monkeypatch, {"jobId": 42, "fee": 500_000, "insuranceCut": 50_000})

    r = await client.post(
        f"/v1/x402/jobs/{job.id}/approve",
        json={},
        headers={"X-Payment-Tx": "0x" + "c" * 64},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["release_tx_hash"] == "0x" + "c" * 64


@pytest.mark.asyncio
async def test_approve_idempotent_when_completed(client, session, monkeypatch) -> None:
    _install_mock_client(monkeypatch)
    requester = _ag("did:agora:r", name="r", payout=None)
    provider = _ag("did:agora:p", name="p", payout="0x" + "9" * 40)
    session.add_all([requester, provider])
    await session.flush()
    job = _onchain_job(requester, provider, status=JobStatus.completed)
    session.add(job)
    await session.commit()

    r = await client.post(f"/v1/x402/jobs/{job.id}/approve", json={})
    # Already done — should just echo the current state, not 402.
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


# ── /jobs/{id}/refund ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refund_returns_402_with_args(client, session, monkeypatch) -> None:
    _install_mock_client(monkeypatch)
    requester = _ag("did:agora:r", name="r", payout=None)
    provider = _ag("did:agora:p", name="p", payout="0x" + "9" * 40)
    session.add_all([requester, provider])
    await session.flush()
    job = _onchain_job(requester, provider, onchain_id=42)
    session.add(job)
    await session.commit()

    r = await client.post(f"/v1/x402/jobs/{job.id}/refund", json={})
    assert r.status_code == 402, r.text
    pr = json.loads(r.headers["X-Payment-Required"])
    assert pr["function"] == "refund"
    assert pr["args"]["jobId"] == "42"
    assert "deadline" in pr["note"].lower()


@pytest.mark.asyncio
async def test_refund_succeeds_with_valid_tx(client, session, monkeypatch) -> None:
    fake = _install_mock_client(monkeypatch)
    _patch_receipt_ok(fake)
    requester = _ag("did:agora:r", name="r", payout=None)
    provider = _ag("did:agora:p", name="p", payout="0x" + "9" * 40)
    session.add_all([requester, provider])
    await session.flush()
    job = _onchain_job(requester, provider, onchain_id=42)
    session.add(job)
    await session.commit()

    _patch_event(monkeypatch, {"jobId": 42})

    r = await client.post(
        f"/v1/x402/jobs/{job.id}/refund",
        json={},
        headers={"X-Payment-Tx": "0x" + "d" * 64},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "refunded"


@pytest.mark.asyncio
async def test_refund_blocked_once_submitted(client, session, monkeypatch) -> None:
    _install_mock_client(monkeypatch)
    requester = _ag("did:agora:r", name="r", payout=None)
    provider = _ag("did:agora:p", name="p", payout="0x" + "9" * 40)
    session.add_all([requester, provider])
    await session.flush()
    job = _onchain_job(requester, provider, status=JobStatus.submitted)
    session.add(job)
    await session.commit()

    r = await client.post(f"/v1/x402/jobs/{job.id}/refund", json={})
    assert r.status_code == 409
