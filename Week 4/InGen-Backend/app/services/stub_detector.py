# Stub detector to confirm API calls and communication
# Returns same prediction every time
from PIL.Image import Image

from app.models.perception import BoundingBox, Detection


class StubDetector:
    def __init__(self) -> None:
        self._loaded = False

    def load(self) -> None:
        self._loaded = True

    def warm_up(self) -> None:
        if not self._loaded:
            raise RuntimeError("Detector must be loaded before warm-up.")

    def predict(self, image: Image) -> list[Detection]:
        if not self._loaded:
            raise RuntimeError("Detector is not loaded.")

        return [
            Detection(
                id="stub_detection_001",
                frame_id="stub_frame",
                class_label="person",
                confidence=0.95,
                bbox=BoundingBox(
                    x=0.25,
                    y=0.20,
                    w=0.20,
                    h=0.50,
                ),
                tracker_id=None,
            )
        ]

    def unload(self) -> None:
        self._loaded = False
