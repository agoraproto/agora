"""Capability discovery routes (Spec Kap. 6.3, 8.1)."""

from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter()


@router.get("/search", summary="Search agents by capability and filters")
async def search_agents(
    capability: str | None = Query(None, examples=["LegalTranslation"]),
    lang: str | None = Query(None, examples=["de:en"]),
    max_price: float | None = None,
    min_reputation: float | None = Query(None, ge=0.0, le=5.0),
    max_latency_ms: int | None = None,
    region: str | None = None,
) -> dict[str, list]:
    """Search agents - combines Typesense text search + Qdrant vector match.

    Spec: §6.3, §8.1
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented - see roadmap Tag 22-35 (Discovery Layer).",
    )


@router.post("/match", summary="Find best-matching agents for a natural task description")
async def match_agents(payload: dict) -> dict[str, list]:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented.",
    )


@router.get("/capabilities", summary="List capability taxonomy")
async def list_capabilities() -> dict[str, list]:
    """Return the current capability taxonomy.

    For MVP this is a static, curated tree (see Spec §6.3).
    """
    return {
        "capabilities": [
            {
                "name": "Translation",
                "children": [
                    "LegalTranslation",
                    "MedicalTranslation",
                    "LiteraryTranslation",
                ],
            },
            {
                "name": "Verification",
                "children": ["FactChecking", "CodeReview", "MathProof"],
            },
            {
                "name": "Generation",
                "children": ["TextGeneration", "ImageGeneration", "CodeGeneration"],
            },
            {"name": "Analysis", "children": []},
            {"name": "Negotiation", "children": []},
            {"name": "Research", "children": []},
        ]
    }
