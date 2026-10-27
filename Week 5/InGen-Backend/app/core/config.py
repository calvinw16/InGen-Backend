# Main place to control configuration values
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Aido Backend"
    environment: str = "development"
    database_url: str = "postgresql://postgres:password@localhost:5432/aido"

    detector_backend: Literal["stub", "yolo"] = "stub"
    yolo_model: str = "yolo11n.pt"
    yolo_confidence_threshold: float = Field(
        default=0.25, ge=0, le=1, allow_inf_nan=False
    )
    yolo_nms_iou_threshold: float = Field(default=0.7, ge=0, le=1, allow_inf_nan=False)
    yolo_max_detections: int = Field(default=300, gt=0)

    latency_metrics_enabled: bool = False

    inference_queue_depth: int = 4
    inference_timeout_seconds: float = 2.0
    retry_after_seconds: int = 1

    # Check for .env file variables
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
