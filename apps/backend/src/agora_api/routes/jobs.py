"""Job lifecycle routes (Spec Kap. 6.4, 8.1, 9.2)."""

from fastapi import APIRouter, HTTPException, status

router = APIRouter()


@router.post("", summary="Create a new job (offer)", status_code=status.HTTP_201_CREATED)
async def create_job(payload: dict) -> dict:
    """Spec: §9.2 step 2 - Offer aus User-Agent an Service-Agent."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented - see roadmap Tag 36-55 (Job Layer).",
    )


@router.get("/{job_id}", summary="Get job status")
async def get_job(job_id: str) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented.",
    )


@router.post("/{job_id}/accept", summary="Service-Agent accepts an offer")
async def accept_job(job_id: str) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented.",
    )


@router.post("/{job_id}/reject", summary="Service-Agent rejects an offer")
async def reject_job(job_id: str) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented.",
    )


@router.post("/{job_id}/result", summary="Submit job result")
async def submit_result(job_id: str, payload: dict) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented.",
    )


@router.post("/{job_id}/approve", summary="Approve and release escrow")
async def approve_job(job_id: str) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented.",
    )


@router.post("/{job_id}/dispute", summary="Open a dispute")
async def open_dispute(job_id: str, payload: dict) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented - see roadmap & Review §3.7 (Trust-Anker).",
    )
