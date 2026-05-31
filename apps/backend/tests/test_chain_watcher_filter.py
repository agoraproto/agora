"""Sprint 36g: chain_watcher must only reconcile jobs whose recorded
escrow_contract_address matches settings.escrow_contract_address.

Legacy NULL rows (created before Sprint 36g) and rows pointing at an
older contract version are skipped, so polling the current contract
with foreign job_ids no longer produces unknown_status log spam.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agora_api.chain.watcher import _sweep_once
from agora_api.db import users_repo
from agora_api.db.models import Agent, AgentStatus, Job, JobStatus, TrustLevel, User


async def _make_agent(session: Any, did: str) -> Agent:
    """Minimal valid User + Agent so the job FK constraints are satisfied."""
    user = User(id=uuid.uuid4(), did=did + ":owner", email=None, settings={})
    session.add(user)
    await session.flush()
    agent = Agent(
        id=uuid.uuid4(),
        did=did,
        owner_did=did,  # self-owned for the test
        name=did.rsplit(":", 1)[-1],
        description="",
        capabilities=[],
        stake_eur=Decimal("0"),
        owner_user_id=user.id,
        trust_level=TrustLevel.probation,
        status=AgentStatus.active,
        did_document={"id": did, "verificationMethod": []},
    )
    session.add(agent)
    await session.flush()
    return agent


def _job(
    requester_id: uuid.UUID,
    provider_id: uuid.UUID,
    *,
    onchain_job_id: int,
    escrow_address: str | None,
) -> Job:
    return Job(
        id=uuid.uuid4(),
        requester_agent_id=requester_id,
        provider_agent_id=provider_id,
        task_spec={},
        status=JobStatus.offered,
        price_amount=Decimal("0.01"),
        price_currency="USDC",
        onchain_job_id=Decimal(onchain_job_id),
        escrow_contract_address=escrow_address,
        settlement_mode="onchain",
        chain="base-sepolia",
    )


@pytest.mark.asyncio
async def test_sweep_filters_by_current_escrow_address(
    session: Any,
    db_sessionmaker: Any,
) -> None:
    """The sweep must only call client.get_job for the matching-address job."""
    # users_repo isn't required here; we just need agents to satisfy FKs.
    _ = users_repo  # keep import alive for linters

    buyer = await _make_agent(session, "did:agora:watcher_buyer")
    provider = await _make_agent(session, "did:agora:watcher_provider")

    current_addr = "0xCurrentV2EscrowAddress00000000000000000"
    legacy_addr = "0xLegacyV1EscrowAddress0000000000000000000"

    # 1) current-address job — MUST be polled
    j_current = _job(buyer.id, provider.id, onchain_job_id=10, escrow_address=current_addr)
    # 2) old-address job — must NOT be polled
    j_old = _job(buyer.id, provider.id, onchain_job_id=20, escrow_address=legacy_addr)
    # 3) NULL legacy job — must NOT be polled
    j_null = _job(buyer.id, provider.id, onchain_job_id=30, escrow_address=None)
    session.add_all([j_current, j_old, j_null])
    await session.commit()

    # Mock the chain client to record which job_ids it sees.
    client = MagicMock()
    polled_ids: list[int] = []

    async def fake_get_job(job_id: int) -> Any:
        polled_ids.append(job_id)
        return MagicMock(status=1)  # 1 = "offered" — matches DB → no drift, returns False

    client.get_job = fake_get_job

    # Patch get_sessionmaker so _sweep_once uses our test DB, and settings
    # so it sees current_addr as the active contract.
    with patch("agora_api.chain.watcher.get_sessionmaker", return_value=db_sessionmaker):
        fake_settings = MagicMock()
        fake_settings.escrow_contract_address = current_addr
        with patch(
            "agora_api.config.get_settings",
            return_value=fake_settings,
        ):
            await _sweep_once(client)

    assert polled_ids == [10], (
        f"only the current-address job (id=10) should be polled, got {polled_ids}"
    )
