from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.perception import BoundingBox, Detection, Frame

# Test if pytest raises validation error when data is formatted incorrectly vs correctly


def test_valid_frame():
    timestamp = datetime.now(UTC)

    frame = Frame(
        id="frame_001",
        robot_id="aido_001",
        platform="aido",
        captured_at=timestamp,
        received_at=timestamp,
        width=1280,
        height=720,
        format="jpeg",
        size_bytes=125000,
        checksum="a" * 64,
    )

    assert frame.width == 1280
    assert frame.robot_id == "aido_001"


def test_invalid_frame_width():
    timestamp = datetime.now(UTC)

    with pytest.raises(ValidationError):
        Frame(
            id="frame_002",
            robot_id="aido_001",
            platform="aido",
            captured_at=timestamp,
            received_at=timestamp,
            width=-100,
            height=720,
            format="jpeg",
            size_bytes=125000,
            checksum="a" * 64,
        )


def test_invalid_bounding_box():
    with pytest.raises(ValidationError):
        BoundingBox(x=0.8, y=0.2, w=0.5, h=0.3)


def test_invalid_confidence():
    with pytest.raises(ValidationError):
        Detection(
            id="det_001",
            frame_id="frame_001",
            class_label="person",
            confidence=1.5,
            bbox=BoundingBox(
                x=0.2,
                y=0.3,
                w=0.4,
                h=0.5,
            ),
        )
