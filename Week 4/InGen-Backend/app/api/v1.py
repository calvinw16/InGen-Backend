import base64
import binascii
import hashlib
from datetime import UTC, datetime
from io import BytesIO
from typing import Annotated, NoReturn
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from app.models.perception import (
    DetectionFilters,
    DetectionListResponse,
    ErrorResponse,
    Frame,
    FrameDetailResponse,
    FrameRequest,
    FrameResponse,
    RobotState,
)

# Use APIRouter to separate endpoints and create modularity

router = APIRouter(prefix="/v1", tags=["Perception"])

# Temporary storage for development phase
# Not implementation of PostgreSQL
frames: dict[str, FrameDetailResponse] = {}

MAX_FRAME_BYTES = 2 * 1024 * 1024


def api_error(
    status_code: int,
    code: str,
    message: str,
) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


@router.post(
    "/frames",  # URL path where the request is sent
    response_model=FrameResponse,
    status_code=status.HTTP_202_ACCEPTED,  # Sets default succesful status code
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
    # 1. Check the encoded payload length before decoding.
    max_base64_chars = 4 * ((MAX_FRAME_BYTES + 2) // 3)

    if len(payload.image_base64) > max_base64_chars:
        api_error(
            413,
            "PAYLOAD_TOO_LARGE",
            "Frame exceeds the 2 MiB limit.",
        )

    # 2. Convert base64 text into image bytes.
    try:
        image_bytes = base64.b64decode(
            payload.image_base64,
            validate=True,
        )
    except (binascii.Error, ValueError):
        api_error(
            422,
            "INVALID_IMAGE",
            "Image is not valid base64.",
        )

    if len(image_bytes) > MAX_FRAME_BYTES:
        api_error(
            413,
            "PAYLOAD_TOO_LARGE",
            "Frame exceeds the 2 MiB limit.",
        )

    # 3. Read the image's actual dimensions.
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.format != "JPEG":
                api_error(
                    422,
                    "UNSUPPORTED_FORMAT",
                    "Only JPEG images are supported.",
                )

            width, height = image.size

            # Force Pillow to decode the image.
            image.load()

    except (UnidentifiedImageError, OSError, ValueError):
        api_error(
            422,
            "INVALID_IMAGE",
            "Image could not be decoded.",
        )

    # 4. Generate server-side metadata.

    frame_id = str(uuid4())
    job_id = str(uuid4())
    received_at = datetime.now(UTC)
    checksum = hashlib.sha256(image_bytes).hexdigest()

    # 5. Construct a complete Pydantic Frame.
    # All Frame validators run automatically here.
    try:
        frame = Frame(
            id=frame_id,
            robot_id=payload.robot_id,
            platform=payload.platform,
            captured_at=payload.timestamp,
            received_at=received_at,
            width=width,
            height=height,
            format="jpeg",
            size_bytes=len(image_bytes),
            checksum=checksum,
        )
    except ValidationError:
        api_error(
            422,
            "INVALID_FRAME_METADATA",
            "Frame metadata failed validation.",
        )

    # 6. Store a temporary frame record.
    # No inference worker is connected yet.
    frames[frame_id] = FrameDetailResponse(
        frame=frame,
        job_id=job_id,
        status="accepted",
        detections=[],
    )

    # 7. Return the documented response.
    return FrameResponse(
        frame_id=frame_id,
        robot_id=frame.robot_id,
        timestamp=frame.captured_at,
        status="accepted",
        job_id=job_id,
        detections=[],
    )


@router.get(
    "/frames/{frame_id}",
    response_model=FrameDetailResponse,
    summary="Retrieve frame information",
    responses={404: {"model": ErrorResponse}},
)
def get_frame(frame_id: str) -> FrameDetailResponse:
    record = frames.get(frame_id)

    if record is None:
        api_error(
            404,
            "FRAME_NOT_FOUND",
            "The requested frame was not found.",
        )

    return record


@router.get(
    "/robots/{robot_id}/state",
    response_model=RobotState,
    summary="Retrieve a robot's current state",
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
    summary="List detection records",
)
def list_detections(
    filters: Annotated[DetectionFilters, Depends()],
) -> DetectionListResponse:
    # Detection storage is not implemented yet.
    return DetectionListResponse(
        items=[],
        count=0,
    )
