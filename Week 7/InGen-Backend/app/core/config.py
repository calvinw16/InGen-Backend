# Main place to control configuration values
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Aido Backend"
    environment: str = "development"
    database_url: str = "sqlite:///./telemetry.db"

    detector_backend: Literal["stub", "yolo"] = "stub"
    yolo_model: str = "yolo11n.pt"
    yolo_confidence_threshold: float = Field(
        default=0.25, ge=0, le=1, allow_inf_nan=False
    )
    yolo_nms_iou_threshold: float = Field(default=0.7, ge=0, le=1, allow_inf_nan=False)
    yolo_max_detections: int = Field(default=300, gt=0)

    state_association_threshold: float = Field(
        default=0.15, ge=0, le=2**0.5, allow_inf_nan=False
    )
    state_stale_seconds: float = Field(default=5, gt=0, allow_inf_nan=False)
    state_eviction_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    state_history_limit: int = Field(default=100, ge=1, le=1000)
    frame_retention_seconds: float = Field(default=3600, gt=0, allow_inf_nan=False)
    fari_frame_retention_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)
    state_history_seconds: float = Field(default=3600, gt=0, allow_inf_nan=False)
    fari_state_history_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)
    state_max_entities: int = Field(default=256, gt=0)

    @model_validator(mode="after")
    def validate_state_windows(self):
        if self.state_eviction_seconds <= self.state_stale_seconds:
            raise ValueError("state_eviction_seconds must exceed state_stale_seconds")
        return self

    max_capture_age_seconds: int = Field(default=86400, gt=0)
    purge_interval_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    purge_dry_run: bool = False

    latency_metrics_enabled: bool = False

    inference_queue_depth: int = 4
    inference_timeout_seconds: float = 2.0
    retry_after_seconds: int = 1

    # Check for .env file variables
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
