#Create appropriate detector model depending on settings in core/config.py
from app.core.config import settings
from app.services.detector import Detector
from app.services.stub_detector import StubDetector
from app.services.yolo_detector import YoloDetector


def create_detector() -> Detector:
    if settings.detector_backend == "stub":
        return StubDetector()

    if settings.detector_backend == "yolo":
        return YoloDetector(
            model_name=settings.yolo_model,
        )

    raise ValueError(
        f"Unsupported detector backend: {settings.detector_backend}"
    )