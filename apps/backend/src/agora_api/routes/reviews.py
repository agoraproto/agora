"""Reputation / review routes (Spec Kap. 6.6, 8.1)."""

from fastapi import APIRouter, HTTPException, status

router = APIRouter()


@router.post("/reviews", summary="Submit a review", status_code=status.HTTP_201_CREATED)
async def submit_review(payload: dict) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented - see roadmap Tag 71-80 (Reputation Layer).",
    )


@router.get("/agents/{did}/reviews", summary="List reviews for an agent")
async def list_reviews(did: str) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented.",
    )


@router.get("/agents/{did}/reputation", summary="Aggregated reputation for an agent")
async def get_reputation(did: str) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented.",
    )
