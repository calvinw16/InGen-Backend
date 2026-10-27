from app.models.perception import (
    Detection,
    FrameDetailResponse,
)

frames: dict[str, FrameDetailResponse] = {}


def save_frame(
    frame_id: str,
    record: FrameDetailResponse,
) -> None:
    frames[frame_id] = record


def get_frame(
    frame_id: str,
) -> FrameDetailResponse | None:
    return frames.get(frame_id)


async def mark_completed(
    frame_id: str,
    detections: list[Detection],
) -> None:
    record = frames.get(frame_id)

    if record is None:
        return

    record.status = "completed"
    record.detections = detections


async def mark_failed(
    frame_id: str,
    error_code: str,
) -> None:
    record = frames.get(frame_id)

    if record is None:
        return

    record.status = "failed"
