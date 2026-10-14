from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Pydantic model is a python class that defines the structureof the data and validates the data with rules specififed


# Frame class represents the data model of frame entering backend for when the backend processes it
class Frame(BaseModel):
    id: str
    robot_id: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    captured_at: datetime
    received_at: datetime
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    format: Literal["jpeg", "png"]
    size_bytes: int = Field(gt=0)
    checksum: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Lowercase SHA-256 hex digest",
    )

    @field_validator("captured_at", "received_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone")

        return value.astimezone(UTC)  # Use UTC as default timezone

    @model_validator(mode="after")
    def validate_timestamp_order(self):
        if self.received_at < self.captured_at:
            raise ValueError("received_at cannot be earlier than captured_at")
        return self


class BoundingBox(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.x + self.w > 1.000001:
            raise ValueError("Bounding box exceeds image width")
        if self.y + self.h > 1.000001:
            raise ValueError("Bounding box exceeds image height")
        return self


# This frame request class ensures the robot_id, timestamp, and image are of correctly listed data types
# FastAPI validates the body against this model
# Defines the data the client will recieve after submitting a frame
class FrameRequest(BaseModel):
    robot_id: str = Field(
        min_length=1,
        description="Identifier of the robot sending the frame",
        examples=["aido_001"],
    )
    platform: str = Field(min_length=1)
    timestamp: datetime = Field(description="UTC timestamp when the frame was captured")
    image_base64: str = Field(min_length=1, description="Base64-encoded JPEG image")


# Inference workers output (normalized)
class Detection(BaseModel):
    id: str
    frame_id: str
    class_label: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    bbox: BoundingBox
    tracker_id: int | None = None


class FrameResponse(BaseModel):
    frame_id: str
    robot_id: str
    timestamp: datetime
    status: Literal["accepted", "processing", "completed", "failed"]
    job_id: str
    detections: list[Detection] = Field(default_factory=list)


class FrameDetailResponse(BaseModel):
    frame: Frame
    job_id: str
    status: Literal["accepted", "processing", "completed", "failed"]
    detections: list[Detection] = Field(default_factory=list)


class RobotState(BaseModel):
    robot_id: str
    state: str
    source: Literal["stub", "robot"]


class DetectionFilters(BaseModel):
    robot_id: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class DetectionRecord(Detection):
    frame_id: str
    robot_id: str


class DetectionListResponse(BaseModel):
    items: list[DetectionRecord]
    count: int


# Specific structure for error response
class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
