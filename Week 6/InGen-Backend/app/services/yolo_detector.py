from typing import Any, cast

from PIL import Image
from pydantic import BaseModel, Field
from ultralytics import YOLO

from app.models.perception import Detection
from app.services.detection_mapping import map_yolo_results


class YoloOptions(BaseModel):
    confidence_threshold: float = Field(default=0.25, ge=0, le=1, allow_inf_nan=False)
    nms_iou_threshold: float = Field(default=0.7, ge=0, le=1, allow_inf_nan=False)
    max_detections: int = Field(default=300, gt=0)


class YoloDetector:
    def __init__(
        self,
        model_name: str = "yolo11n.pt",
        *,
        confidence_threshold: float = 0.25,
        nms_iou_threshold: float = 0.7,
        max_detections: int = 300,
    ) -> None:
        self.model_name = model_name
        self.model: YOLO | None = None
        self.options = YoloOptions(
            confidence_threshold=confidence_threshold,
            nms_iou_threshold=nms_iou_threshold,
            max_detections=max_detections,
        )

    def load(self) -> None:
        self.model = YOLO(self.model_name)

    def warm_up(self) -> None:
        if self.model is None:
            raise RuntimeError("Detector must be loaded before warm-up.")
        self.predict(Image.new("RGB", (640, 640), "black"))

    def predict(self, image: Image.Image) -> list[Detection]:
        if self.model is None:
            raise RuntimeError("Detector is not loaded.")
        results = cast(
            list[Any],
            self.model.predict(
                source=image,
                verbose=False,
                conf=self.options.confidence_threshold,
                iou=self.options.nms_iou_threshold,
                agnostic_nms=False,
                max_det=self.options.max_detections,
            ),
        )
        return map_yolo_results(results, self.options.confidence_threshold)

    def unload(self) -> None:
        self.model = None
