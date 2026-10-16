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

from app.core.runtime import worker
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
from app.services.frame_store import (
    get_frame as get_frame_record,
)
from app.services.frame_store import (
    mark_completed,
    mark_failed,
    save_frame,
)
from app.workers.detection_worker import (
    QueueFullError,
    WorkerNotReadyError,
)
from app.workers.models import InferenceJob

# API router
router = APIRouter(prefix="/v1", tags=["Perception"])

# Maximum accepted image size: 2 MiB
MAX_FRAME_BYTES = 2 * 1024 * 1024


def api_error(
    status_code: int,
    code: str,
    message: str,
) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
        },
    )


@router.post(
    "/frames",
    response_model=FrameResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a frame for inference",
    description=(
        "Accepts a base64-encoded JPEG frame, validates "
        "the image, saves a temporary frame record, and "
        "queues the frame for asynchronous inference."
    ),
    responses={
        413: {
            "model": ErrorResponse,
            "description": "Image exceeds 2 MiB",
        },
        422: {
            "description": "Invalid request payload",
        },
        503: {
            "model": ErrorResponse,
            "description": "Inference worker unavailable or queue full",
        },
    },
)
async def submit_frame(
    payload: FrameRequest,
) -> FrameResponse:

    # 1. Check encoded payload length before decoding.
    max_base64_chars = 4 * ((MAX_FRAME_BYTES + 2) // 3)

    if len(payload.image_base64) > max_base64_chars:
        api_error(
            413,
            "PAYLOAD_TOO_LARGE",
            "Frame exceeds the 2 MiB limit.",
        )

    # 2. Decode base64 image.
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

    # 3. Validate image format and decode JPEG.
    try:
        with Image.open(BytesIO(image_bytes)) as image:

            if image.format != "JPEG":
                api_error(
                    422,
                    "UNSUPPORTED_FORMAT",
                    "Only JPEG images are supported.",
                )

            width, height = image.size

            # Force Pillow to decode image data.
            image.load()

            # Preserve image after the file is closed.
            decoded_image = image.copy()

    except (UnidentifiedImageError, OSError, ValueError):
        api_error(
            422,
            "INVALID_IMAGE",
            "Image could not be decoded.",
        )

    # 4. Generate frame metadata.
    frame_id = str(uuid4())
    job_id = str(uuid4())

    received_at = datetime.now(UTC)

    checksum = hashlib.sha256(image_bytes).hexdigest()

    # 5. Construct validated Frame model.
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

    # 6. Create frame record.
    record = FrameDetailResponse(
        frame=frame,
        job_id=job_id,
        status="accepted",
        detections=[],
    )

    # 7. Create inference job with callbacks.
    job = InferenceJob(
        frame_id=frame_id,
        image=decoded_image,
        on_completed=mark_completed,
        on_failed=mark_failed,
    )

    # 8. Save frame record before submitting inference.
    save_frame(frame_id, record)

    # 9. Enqueue inference job.
    try:
        await worker.enqueue(job)

    except WorkerNotReadyError:
        await mark_failed(
            frame_id,
            "WORKER_NOT_READY",
        )

        api_error(
            503,
            "WORKER_NOT_READY",
            "Inference worker is not ready.",
        )

    except QueueFullError:
        await mark_failed(
            frame_id,
            "QUEUE_FULL",
        )

        api_error(
            503,
            "QUEUE_FULL",
            "Inference queue is full.",
        )

    # 10. Return immediately after successful enqueue.
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
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Frame not found",
        },
    },
)
def get_frame(
    frame_id: str,
) -> FrameDetailResponse:

    record = get_frame_record(frame_id)

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
def get_robot_state(
    robot_id: str,
) -> RobotState:

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
    filters: Annotated[
        DetectionFilters,
        Depends(),
    ],
) -> DetectionListResponse:

    # Detection listing is not implemented yet.
    return DetectionListResponse(
        items=[],
        count=0,
    )
