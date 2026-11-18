from datetime import time
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, model_validator

from app.models.perception import BoundingBox

Label = Annotated[str, Field(min_length=1, max_length=80)]
Severity = Literal["info", "warning", "critical"]


class UTCWindow(BaseModel):
    start: time
    end: time

    @model_validator(mode="after")
    def valid_window(self):
        if self.start.tzinfo or self.end.tzinfo or self.start == self.end:
            raise ValueError("Use distinct UTC clock times without offsets")
        return self

    def includes(self, value: time) -> bool:
        if self.start < self.end:
            return self.start <= value < self.end
        return value >= self.start or value < self.end


class Rule(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    enabled: bool = True
    robot_id: Label | None = None
    platform: Label | None = None
    class_labels: set[Label] = Field(min_length=1, max_length=80)
    min_confidence: float = Field(default=0.5, ge=0, le=1)
    zone: BoundingBox | None = None
    utc_window: UTCWindow | None = None
    consecutive_frames: int = Field(default=1, ge=1, le=1000)
    severity: Severity = "warning"
    cooldown_seconds: int = Field(default=60, ge=0, le=86400)


class Subscriber(BaseModel):
    url: HttpUrl
    secret: SecretStr = Field(min_length=32, max_length=512)


class Acknowledgement(BaseModel):
    actor: Annotated[str, Field(min_length=1, max_length=120)]
