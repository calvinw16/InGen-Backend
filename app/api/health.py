# Health Router Connected to App
# Check if application process is alive
from fastapi import APIRouter, HTTPException

router = APIRouter()


def dependency_is_ready() -> bool:
    # Replace with actual database/worker check
    return True


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/readyz")
def readyz():
    if not dependency_is_ready():
        raise HTTPException(status_code=503, detail="Service not ready")

    return {"status": "ready"}
