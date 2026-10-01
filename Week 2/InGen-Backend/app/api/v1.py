import base64
import binascii
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

# Import classes from perception
from app.models.perception import (
    DetectionFilters,
    DetectionListResponse,
    ErrorResponse,
    FrameRequest,
    FrameResponse,
    RobotState,
)

# Use APIRouter to separate endpoints and create modularity

router = APIRouter(prefix="/v1", tags=["Perception"])

# Temporary storage for development phase
# Not implementation of PostgreSQL
frames: dict[str, FrameResponse] = {}

MAX_FRAME_BYTES = 2 * 1024 * 1024


@router.post(
    "/frames",  # URL path where the request is sent
    response_model=FrameResponse,
    status_code=202,  # Sets default succesful status code
    summary="Submit a frame for inference",
    description=(
        "Accepts a base64-encoded JPEG frame and creates a "
        "temporary processing record. Worker dispatch is not "
        "implemented in this initial version."
    ),
    responses={
        413: {
            "model": ErrorResponse,
            "description": "Image exceeds 2 MiB",
        },
        422: {"description": "Invalid request payload"},
    },
)
def submit_frame(payload: FrameRequest) -> FrameResponse:
    try:
        image_bytes = base64.b64decode(payload.image_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=422,
            detail="Invalid base64 image payload",
        ) from None

    if len(image_bytes) > MAX_FRAME_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Image exceeds maximum payload size",
        )

    if not image_bytes.startswith(b"\xff\xd8\xff"):
        raise HTTPException(
            status_code=422,
            detail="Expected a JPEG image",
        )

    frame_id = str(uuid4())

    record = FrameResponse(
        frame_id=frame_id,
        robot_id=payload.robot_id,
        timestamp=payload.timestamp,
        status="accepted",
        job_id=frame_id,
        detections=[],
    )

    frames[frame_id] = record
    return record


@router.get(
    "/frames/{frame_id}",  # URL path the client requests to access
    response_model=FrameResponse,  # Required formatting of data
    summary="Retrieve a submitted frame",
    description=(
        "Returns frame metadata, processing status, and available "
        "detections. The current implementation uses temporary memory."
    ),
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Frame not found",
        }
    },
)
def get_frame(frame_id: str) -> FrameResponse:
    record = frames.get(frame_id)  # Should be a PostgreSQL database

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Frame not found",
        )

    return record


@router.get(
    "/robots/{robot_id}/state",
    response_model=RobotState,
    summary="Retrieve robot state",
    description=(
        "Returns a stubbed robot state. Real state integration "
        "is planned for Week 4."
    ),
)
def get_robot_state(robot_id: str) -> RobotState:
    return RobotState(
        robot_id=robot_id,
        state="unknown",
        source="stub",
    )


@router.get(
    "/detections",
    response_model=DetectionListResponse,
    summary="List detections",
    description=(
        "Declares robot filtering and pagination limit. "
        "Persistent detection retrieval is not implemented yet."
    ),
)
def list_detections(
    filters: Annotated[DetectionFilters, Depends()],
) -> DetectionListResponse:
    return DetectionListResponse(items=[], count=0)
