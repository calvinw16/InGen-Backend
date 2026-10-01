from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Pydantic model is a python class that defines the structureof the data and validates the data with rules specififed


# This frame request class ensures the robot_id, timestamp, and image are of correctly listed data types
# FastAPI validates the body against this model
# Defines the data the client will recieve after submitting a frame
class FrameRequest(BaseModel):
    robot_id: str = Field(
        min_length=1,
        description="Identifier of the robot sending the frame",
        examples=["aido_001"],
    )
    timestamp: datetime = Field(description="UTC timestamp when the frame was captured")
    image_base64: str = Field(min_length=1, description="Base64-encoded JPEG image")


class Detection(BaseModel):
    label: str
    confidence: float = Field(ge=0, le=1)
    bbox: list[int] = Field(
        description="Bounding box [xmin, ymin, xmax, ymax] in pixels"
    )


class FrameResponse(BaseModel):
    frame_id: str
    robot_id: str
    timestamp: datetime
    status: Literal["accepted", "processing", "completed", "failed"]
    job_id: str
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


class ErrorResponse(BaseModel):
    detail: str
