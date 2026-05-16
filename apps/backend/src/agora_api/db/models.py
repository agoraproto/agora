"""ORM models for Agora.

Cross-DB-compatible: uses portable SQLAlchemy types (Uuid, JSON) instead of
Postgres-specific ones, so the same schema runs on Postgres (prod) and
SQLite (tests / dev). Postgres-specific tuning (JSONB indexes, etc.) is
added in Alembic migrations once needed.

Spec ref: §7.1, plus ADR 003/004/006/007/008 fields.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base


class AgentType(str, enum.Enum):
    service = "service"
    user = "user"
    hybrid = "hybrid"


class TrustLevel(str, enum.Enum):
    probation = "probation"
    new = "new"
    verified = "verified"
    trusted = "trusted"
    banned = "banned"


class AgentStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    deprecated = "deprecated"
    archived = "archived"
    banned = "banned"


class JobStatus(str, enum.Enum):
    offered = "offered"
    accepted = "accepted"
    in_progress = "in_progress"
    submitted = "submitted"
    completed = "completed"
    disputed = "disputed"
    cancelled = "cancelled"
    refunded = "refunded"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    failed = "failed"


class DisputeStatus(str, enum.Enum):
    open = "open"
    resolved_for_requester = "resolved_for_requester"
    resolved_for_provider = "resolved_for_provider"
    escalated = "escalated"


class LedgerEntryType(str, enum.Enum):
    deposit = "deposit"
    escrow_hold = "escrow_hold"
    escrow_release = "escrow_release"
    platform_fee = "platform_fee"
    insurance_fee = "insurance_fee"
    refund = "refund"
    sponsor_slash = "sponsor_slash"
    withdraw = "withdraw"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    did: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    agents: Mapped[list[Agent]] = relationship(back_populates="owner")


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    did: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    owner_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    type: Mapped[AgentType] = mapped_column(Enum(AgentType), default=AgentType.service)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    public_endpoint: Mapped[str | None] = mapped_column(Text)
    capabilities: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    pricing: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    did_document: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    stake_eur: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    sponsor_did: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sponsor_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    trust_level: Mapped[TrustLevel] = mapped_column(
        Enum(TrustLevel), default=TrustLevel.probation
    )

    webhook_secret_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[AgentStatus] = mapped_column(Enum(AgentStatus), default=AgentStatus.active)

    # Reputation cache (Sprint 4): aggregated from `reviews`. Source-of-truth
    # is the reviews table; these columns let listings stay cheap.
    reputation_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    reputation_count: Mapped[int] = mapped_column(default=0, nullable=False)
    jobs_completed: Mapped[int] = mapped_column(default=0, nullable=False)

    owner: Mapped[User | None] = relationship(back_populates="agents")
    credentials: Mapped[list[Credential]] = relationship(back_populates="agent")


class Credential(Base, TimestampMixin):
    __tablename__ = "credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agents.id"), nullable=False)
    issuer_did: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    claim: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[Agent] = relationship(back_populates="credentials")


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    requester_agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agents.id"), nullable=False
    )
    provider_agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agents.id"), nullable=False
    )
    task_spec: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.offered)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    price_currency: Mapped[str] = mapped_column(String(8), default="EURC")
    escrow_tx_hash: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LedgerBalance(Base, TimestampMixin):
    __tablename__ = "ledger_balances"

    agent_did: Mapped[str] = mapped_column(String(255), primary_key=True)
    currency: Mapped[str] = mapped_column(String(8), primary_key=True, default="EURC")
    available: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    in_escrow: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)


class LedgerEntry(Base, TimestampMixin):
    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    entry_type: Mapped[LedgerEntryType] = mapped_column(Enum(LedgerEntryType), nullable=False)
    delta_available: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    delta_escrow: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("jobs.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id"), nullable=False)
    from_agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agents.id"), nullable=False)
    to_agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agents.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    chain: Mapped[str] = mapped_column(String(32), default="base-sepolia")
    tx_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), default=PaymentStatus.pending
    )


class Review(Base, TimestampMixin):
    """5-dimension review (Spec §6.6). scores is a JSON dict with keys
    accuracy, speed, cost, reliability, communication — each 1.0..5.0.
    """

    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id"), nullable=False)
    reviewer_agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agents.id"), nullable=False
    )
    reviewee_agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agents.id"), nullable=False, index=True
    )
    scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    comment: Mapped[str | None] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(Text, default="")
    aggregate_score: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)


class Dispute(Base, TimestampMixin):
    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id"), nullable=False)
    raised_by_agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agents.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[DisputeStatus] = mapped_column(Enum(DisputeStatus), default=DisputeStatus.open)
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
