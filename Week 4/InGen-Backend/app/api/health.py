# Health Router Connected to App
# Check if application process is alive
from fastapi import APIRouter, HTTPException, status

from app.core.runtime import worker

router = APIRouter()


@router.get(
    "/healthz",
    summary="Liveness check",
    description="Returns 200 when the API process is alive.",
)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/readyz",
    summary="Readiness check",
    description=(
        "Returns 200 only when the inference worker has loaded "
        "and warmed the configured detector."
    ),
)
def readyz() -> dict[str, str | int]:
    if not worker.ready or not worker.healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inference worker is not ready.",
        )

    return {
        "status": "ready",
        "queue_depth": worker.queue.qsize(),
    }
