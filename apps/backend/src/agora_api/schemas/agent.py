"""Agent schemas (Spec Kap. 6.2, 6.3)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentCapability(BaseModel):
    """A single capability declared by an agent."""

    type: str = Field(..., examples=["LegalTranslation"])
    params: dict[str, Any] = Field(default_factory=dict)
    specializations: list[str] = Field(default_factory=list)
    verified_by: list[str] = Field(default_factory=list, description="List of issuer DIDs")


class AgentPricing(BaseModel):
    """Pricing declaration. See Spec §21.15 for extended models."""

    model: Literal["per_request", "per_token", "per_minute", "subscription", "auction"] = (
        "per_request"
    )
    currency: Literal["USDC", "EURC"] = "EURC"
    base_price: str = Field(..., examples=["0.05"])
    negotiable: bool = False


class AgentConstraints(BaseModel):
    max_requests_per_minute: int | None = None
    max_concurrent: int | None = None
    regions: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


class AgentRegisterRequest(BaseModel):
    """Payload to register a new agent."""

    did_document: dict[str, Any] = Field(
        ..., description="W3C DID document (id, verificationMethod, service)"
    )
    name: str
    description: str
    owner_did: str
    capabilities: list[AgentCapability]
    pricing: AgentPricing
    constraints: AgentConstraints = Field(default_factory=AgentConstraints)
    endpoint_url: str


class AgentRegisterResponse(BaseModel):
    did: str
    status: Literal["draft", "active"]
    registered_at: datetime


class AgentProfile(BaseModel):
    """Public-facing agent profile (Spec §6.3)."""

    did: str
    name: str
    description: str
    owner: str
    capabilities: list[AgentCapability]
    pricing: AgentPricing
    constraints: AgentConstraints
    reputation_score: float | None = None
    total_reviews: int = 0
    trust_level: Literal["new", "verified", "trusted"] = "new"
    status: Literal["draft", "active", "paused", "deprecated", "archived", "banned"] = "active"
