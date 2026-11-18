from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.models.perception import (
    Detection,
    FrameDetailResponse,
)
from app.services import telemetry_store
from app.services.retention import retention_policy
from app.services.robot_state import robot_states

frames: dict[str, FrameDetailResponse] = {}


def purge_expired(now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    for frame_id, record in list(frames.items()):
        if record._expires_at is not None and record._expires_at <= now:
            frames.pop(frame_id, None)


def expire_after_completion(record: FrameDetailResponse) -> None:
    ttl = retention_policy(record.frame.platform).frame_seconds
    record._expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
    purge_expired()


def save_frame(
    frame_id: str,
    record: FrameDetailResponse,
) -> None:
    purge_expired()
    telemetry_store.save(record)
    frames[frame_id] = record


def get_frame(
    frame_id: str,
) -> FrameDetailResponse | None:
    purge_expired()
    return frames.get(frame_id) or telemetry_store.get_frame(frame_id)


async def mark_completed(
    frame_id: str,
    detections: list[Detection],
) -> None:
    record = frames.get(frame_id)

    if record is None:
        return

    cleaned = [
        d.model_copy(update={"id": str(uuid4())})
        for d in telemetry_store.clean_detections(detections)
    ]
    completed = record.model_copy(update={"status": "completed", "detections": cleaned})
    try:
        robot_states.update(
            record.frame.robot_id,
            frame_id,
            cleaned,
            platform=record.frame.platform,
            persist=lambda state: telemetry_store.finish(completed, state),
        )
    except SQLAlchemyError:
        await mark_failed(frame_id, "TELEMETRY_WRITE_FAILED")
        return
    record.status = "completed"
    record.detections = cleaned
    expire_after_completion(record)


async def mark_failed(
    frame_id: str,
    error_code: str,
) -> None:
    record = frames.get(frame_id)

    if record is None:
        return

    try:
        telemetry_store.finish(
            record.model_copy(update={"status": "failed"}), error=error_code
        )
    except SQLAlchemyError:
        telemetry_store.log.exception("frame_failure_persistence_failed")
    record.status = "failed"
    expire_after_completion(record)
