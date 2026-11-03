from datetime import UTC, datetime, timedelta

from app.models.perception import (
    Detection,
    FrameDetailResponse,
)
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
    frames[frame_id] = record


def get_frame(
    frame_id: str,
) -> FrameDetailResponse | None:
    purge_expired()
    return frames.get(frame_id)


async def mark_completed(
    frame_id: str,
    detections: list[Detection],
) -> None:
    record = frames.get(frame_id)

    if record is None:
        return

    robot_states.update(
        record.frame.robot_id, frame_id, detections, platform=record.frame.platform
    )
    record.status = "completed"
    record.detections = detections
    expire_after_completion(record)


async def mark_failed(
    frame_id: str,
    error_code: str,
) -> None:
    record = frames.get(frame_id)

    if record is None:
        return

    record.status = "failed"
    expire_after_completion(record)
