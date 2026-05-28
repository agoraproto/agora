"""ORM models for Agora.

Cross-DB-compatible: uses portable SQLAlchemy types (Uuid, JSON) instead of
Postgres-specific ones, so the same schema runs on Postgres (prod) and
SQLite (tests / dev).

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
    # M-04 audit fix: V2 contract status 6 = Resolved (after resolveDispute).
    # Terminal state — dispute was settled with a payee/payer split.
    resolved = "resolved"


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


class WebhookDeliveryStatus(str, enum.Enum):
    pending = "pending"
    delivering = "delivering"
    delivered = "delivered"
    failed = "failed"
    exhausted = "exhausted"


class ServiceRequestStatus(str, enum.Enum):
    """Sprint 31: lifecycle states for a demand-side request-for-quote."""
    open = "open"
    accepted = "accepted"
    closed = "closed"
    cancelled = "cancelled"


class BidStatus(str, enum.Enum):
    """Sprint 31: lifecycle states for a provider's bid against an RFQ."""
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    expired = "expired"



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

    # ── Privy auth linkage (Sprint 10d) ──
    # Privy's user.id (their stable identifier; not an email). When set,
    # the User row was created via Privy login and is fully authenticated.
    # Nullable so legacy seeded users (alice-demo) continue to exist.
    privy_user_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    # Primary EVM address the user holds via Privy embedded wallet (or a
    # bring-your-own external wallet linked through Privy). Used as the
    # default payout_wallet when this user creates a listing.
    primary_wallet: Mapped[str | None] = mapped_column(String(64), nullable=True)

    agents: Mapped[list[Agent]] = relationship(back_populates="owner")


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    did: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    owner_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    type: Mapped[AgentType] = mapped_column(Enum(AgentType, native_enum=False), default=AgentType.service)
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
        Enum(TrustLevel, native_enum=False), default=TrustLevel.probation
    )

    webhook_secret_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[AgentStatus] = mapped_column(Enum(AgentStatus, native_enum=False), default=AgentStatus.active)
    # EVM address (0x...) where on-chain escrow releases pay out.
    payout_wallet: Mapped[str | None] = mapped_column(String(64), nullable=True)

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
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, native_enum=False), default=JobStatus.offered)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    # Sprint 18c: default "USDC" — all on-chain x402 jobs settle in USDC.
    # Pre-Sprint-11 ledger jobs persist as "EURC" in existing rows, but
    # everything created from now on is USDC-denominated.
    price_currency: Mapped[str] = mapped_column(String(8), default="USDC")
    escrow_tx_hash: Mapped[str | None] = mapped_column(Text)
    release_tx_hash: Mapped[str | None] = mapped_column(Text)
    # uint256 jobId returned by AgoraEscrow.createJob(); Numeric(78,0) fits 2**256.
    onchain_job_id: Mapped[Decimal | None] = mapped_column(Numeric(78, 0), index=True)
    # "offchain" = ledger-only (bootstrap mode); "onchain" = settled via AgoraEscrow.
    settlement_mode: Mapped[str] = mapped_column(String(16), default="offchain", nullable=False)
    chain: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sprint 10c: marketplace purchase trail. When a job is created
    # through the marketplace Buy flow, we record which Listing it came
    # from so the delivery endpoint can release digital_content only to
    # the legitimate buyer.
    listing_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("listings.id"), nullable=True, index=True
    )


class LedgerBalance(Base, TimestampMixin):
    __tablename__ = "ledger_balances"

    agent_did: Mapped[str] = mapped_column(String(255), primary_key=True)
    # Sprint 18c: new ledger balances default to USDC, matching on-chain.
    currency: Mapped[str] = mapped_column(String(8), primary_key=True, default="USDC")
    available: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    in_escrow: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)


class LedgerEntry(Base, TimestampMixin):
    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    entry_type: Mapped[LedgerEntryType] = mapped_column(Enum(LedgerEntryType, native_enum=False), nullable=False)
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
        Enum(PaymentStatus, native_enum=False), default=PaymentStatus.pending
    )


class Review(Base, TimestampMixin):
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
    status: Mapped[DisputeStatus] = mapped_column(Enum(DisputeStatus, native_enum=False), default=DisputeStatus.open)
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ListingKind(str, enum.Enum):
    """What kind of seller a Listing belongs to."""

    agent = "agent"
    user = "user"


class ListingType(str, enum.Enum):
    """A Listing is either a service offer or a pre-computed digital product.

    `service`: when bought, a Job is created from the listing's spec; the
    seller (agent or human) fulfills it via the usual submitResult flow.

    `digital_product`: when bought, the listing's pre-computed
    `digital_content` is delivered to the buyer immediately on
    `approveAndPay`. No work performed at sale time.
    """

    service = "service"
    digital_product = "digital_product"


class ListingStatus(str, enum.Enum):
    active = "active"     # visible in search, buyable
    paused = "paused"     # hidden from search, existing orders unaffected
    archived = "archived" # gone from search forever; preserved for receipts


class Listing(Base, TimestampMixin):
    """A marketplace listing — Sprint 10 / Etsy-for-AI direction.

    A Listing is offered by either an Agent (via SDK) or a human User
    (via web login). Pricing is USDC-denominated and paid through the
    same x402 escrow flow as Jobs.

    Service listings are essentially Job-templates: buying creates a
    Job whose task_spec the buyer fills in per `service_input_schema`.

    Digital-product listings carry their deliverable in
    `digital_content`. Buying triggers an x402 flow that, on approval,
    releases the content to the buyer's order record. No background
    work between hire and approve — the result is the same every time.
    """

    __tablename__ = "listings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # ── Seller ──
    seller_kind: Mapped[ListingKind] = mapped_column(
        Enum(ListingKind, native_enum=False), nullable=False, index=True
    )
    # DID of the agent or user offering this listing. Stored as a string
    # (not a FK) so a single column can reference both `agents.did` and
    # `users.did`. The API layer validates that the DID exists.
    seller_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # EVM address that receives the USDC payout on approval.
    payout_wallet: Mapped[str] = mapped_column(String(64), nullable=False)

    # ── What it is ──
    listing_type: Mapped[ListingType] = mapped_column(
        Enum(ListingType, native_enum=False), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Free-form taxonomy. Suggested values: 'translation', 'image-gen',
    # 'code-review', 'fact-check', 'data-analysis', 'prompts',
    # 'datasets', 'templates', 'tutorials', 'custom-gpts'.
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="other", index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # ── Pricing (USDC) ──
    price_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    price_currency: Mapped[str] = mapped_column(String(8), default="USDC", nullable=False)

    # ── Service-specific ──
    # The capability tag a service performs (e.g. 'Translation'). Empty for
    # digital products. Used for capability-based search.
    service_capability: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # JSON Schema (or just a plain dict) describing what the buyer must
    # provide as the task spec when they hire. Empty for digital products.
    service_input_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # ── Digital-product specific ──
    # MIME-ish type of the deliverable, for the UI to render correctly:
    # 'text/plain', 'text/markdown', 'application/json', 'file_url',
    # 'ipfs_cid'. Empty for services.
    digital_content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The deliverable payload. Format depends on `digital_content_type`.
    # For 'text/markdown' it's {"text": "..."}; for 'file_url' it's
    # {"url": "https://...", "filename": "..."}; etc.
    digital_content: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # ── Presentation ──
    cover_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    images: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # ── State ──
    status: Mapped[ListingStatus] = mapped_column(
        Enum(ListingStatus, native_enum=False),
        default=ListingStatus.active,
        nullable=False,
        index=True,
    )

    # ── Stats (denormalised; updated on each completed order) ──
    sales_count: Mapped[int] = mapped_column(default=0, nullable=False)
    rating_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    rating_count: Mapped[int] = mapped_column(default=0, nullable=False)


class WebhookDelivery(Base, TimestampMixin):
    """Persistent webhook delivery queue (Sprint 6 / ADR 008)."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agents.id"), nullable=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("jobs.id"), nullable=True, index=True
    )

    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    endpoint_url: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    status: Mapped[WebhookDeliveryStatus] = mapped_column(
        Enum(WebhookDeliveryStatus, native_enum=False),
        default=WebhookDeliveryStatus.pending,
        nullable=False,
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    last_response_status: Mapped[int | None] = mapped_column(default=None, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

class ServiceRequest(Base, TimestampMixin):
    """Sprint 31: demand-side RFQ posted by a buyer agent.

    The buyer publishes a request for a capability; providers can submit
    cryptographically-signed bids. When the buyer accepts a bid, a normal
    x402 hire is triggered against the winning provider.
    """

    __tablename__ = "service_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    buyer_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    capability: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    max_price_micro_usdc: Mapped[int] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USDC", nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[ServiceRequestStatus] = mapped_column(
        Enum(ServiceRequestStatus, native_enum=False),
        default=ServiceRequestStatus.open,
        nullable=False,
        index=True,
    )
    accepted_bid_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class Bid(Base, TimestampMixin):
    """Sprint 31: provider bid against a ServiceRequest.

    The immutable canonical payload plus Ed25519 signature are persisted
    so buyers, providers, and later dispute tooling can audit what was
    actually offered.
    """

    __tablename__ = "bids"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service_requests.id"), nullable=False, index=True
    )
    provider_did: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    price_micro_usdc: Mapped[int] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USDC", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    signed_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    bid_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[BidStatus] = mapped_column(
        Enum(BidStatus, native_enum=False),
        default=BidStatus.pending,
        nullable=False,
        index=True,
    )

