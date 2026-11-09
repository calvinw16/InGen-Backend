import base64
import binascii
import hashlib
from datetime import UTC, datetime
from io import BytesIO
from time import perf_counter
from typing import Annotated, NoReturn
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import AwareDatetime, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.runtime import worker
from app.models.perception import (
    DetectionListResponse,
    ErrorResponse,
    Frame,
    FrameDetailResponse,
    FrameRequest,
    FrameResponse,
    RobotState,
    RobotStateHistory,
)
from app.services.frame_store import (
    get_frame as get_frame_record,
)
from app.services.frame_store import (
    mark_completed,
    mark_failed,
    save_frame,
)
from app.services.robot_state import robot_states
from app.services.telemetry_query import (
    DetectionQuery,
    query_detections,
    query_timeline,
)
from app.services.telemetry_store import flag, quality_stats
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

    received_at = datetime.now(UTC)
    if payload.timestamp.utcoffset() is None:
        api_error(
            422, "TIMESTAMP_TIMEZONE_REQUIRED", "Timestamp must include a timezone."
        )
    if payload.timestamp > received_at:
        flag("future_timestamp")
        api_error(422, "FUTURE_TIMESTAMP", "Capture timestamp is in the future.")
    if (
        received_at - payload.timestamp
    ).total_seconds() > settings.max_capture_age_seconds:
        flag("old_timestamp")
        api_error(
            422, "OLD_TIMESTAMP", "Capture timestamp exceeds maximum accepted age."
        )
    decode_started = perf_counter()

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

    decode_ms = (perf_counter() - decode_started) * 1000

    # 4. Generate frame metadata.
    frame_id = str(uuid4())
    job_id = str(uuid4())

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

    if settings.latency_metrics_enabled:
        record._timings["decode_ms"] = decode_ms

    # 7. Create inference job with callbacks.
    job = InferenceJob(
        frame_id=frame_id,
        image=decoded_image,
        on_completed=mark_completed,
        on_failed=mark_failed,
        timings=record._timings,
    )

    # 8. Save frame record before submitting inference.
    try:
        save_frame(frame_id, record)
    except SQLAlchemyError:
        decoded_image.close()
        api_error(
            503, "TELEMETRY_UNAVAILABLE", "Frame metadata could not be persisted."
        )

    # 9. Enqueue inference job.
    try:
        await worker.enqueue(job)

    except WorkerNotReadyError:
        decoded_image.close()
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
        decoded_image.close()
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
) -> FrameDetailResponse | Response:

    record = get_frame_record(frame_id)

    if record is None:
        api_error(
            404,
            "FRAME_NOT_FOUND",
            "The requested frame was not found.",
        )

    if settings.latency_metrics_enabled:
        started = perf_counter()
        content = record.model_dump_json()
        serialization_ms = (perf_counter() - started) * 1000
        timings = {**record._timings, "serialization_ms": serialization_ms}
        return Response(
            content=content,
            media_type="application/json",
            headers={f"X-Latency-{key}": str(value) for key, value in timings.items()},
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

    return robot_states.get(robot_id)


@router.get("/robots/{robot_id}/state/history", response_model=RobotStateHistory)
def get_robot_state_history(
    robot_id: str,
    limit: Annotated[int, Query(ge=1, le=1000)] = 20,
) -> RobotStateHistory:
    items = robot_states.history(robot_id, limit)
    return RobotStateHistory(robot_id=robot_id, items=items, count=len(items))


@router.get(
    "/detections",
    response_model=DetectionListResponse,
    summary="List detection records",
)
def list_detections(
    filters: Annotated[DetectionQuery, Query()],
) -> DetectionListResponse:
    try:
        return DetectionListResponse.model_validate(query_detections(filters))
    except ValueError as exc:
        api_error(422, "INVALID_CURSOR", str(exc))


@router.get("/robots/{robot_id}/timeline")
def get_timeline(
    robot_id: str,
    start: AwareDatetime,
    end: AwareDatetime,
    bucket_seconds: Annotated[int, Query(ge=60, le=86400)] = 3600,
):
    if not 0 < (end - start).total_seconds() <= 31 * 86400:
        api_error(
            422,
            "INVALID_TIME_RANGE",
            "Timeline requires an increasing range of at most 31 days.",
        )
    return query_timeline(robot_id, start, end, bucket_seconds)


@router.get("/admin/stats")
def admin_stats():
    return {"data_quality": quality_stats()}
