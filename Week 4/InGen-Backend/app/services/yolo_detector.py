from typing import Any, cast
from uuid import uuid4

from PIL import Image
from ultralytics import YOLO

from app.models.perception import BoundingBox, Detection


class YoloDetector:
    def __init__(self, model_name: str = "yolo11n.pt") -> None:
        self.model_name = model_name
        self.model: YOLO | None = None

    def load(self) -> None:
        self.model = YOLO(self.model_name)

    # To account for slower inference initially due to initializing internal resources
    # Or allocating memory
    def warm_up(self) -> None:
        if self.model is None:
            raise RuntimeError("Detector must be loaded before warm-up.")

        warmup_image = Image.new(
            "RGB",
            (640, 640),
            "black",
        )

        self.model.predict(
            source=warmup_image,
            verbose=False,
        )

    def predict(self, image: Image.Image) -> list[Detection]:
        if self.model is None:
            raise RuntimeError("Detector is not loaded.")

        results = cast(
            list[Any],
            self.model.predict(
            source=image,
            verbose=False,
        ))

        detections: list[Detection] = []

        for result in results:
            image_height, image_width = result.orig_shape

            if result.boxes is None:
                continue
            
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                class_id = int(box.cls[0])
                confidence = float(box.conf[0])

                detections.append(
                    Detection(
                        id=str(uuid4()),
                        frame_id="pending",  # Change to recieve a frame ID or attach the frame ID after inference in a service layer
                        class_label=result.names[class_id],
                        confidence=confidence,
                        bbox=BoundingBox(
                            x=x1 / image_width,
                            y=y1 / image_height,
                            w=(x2 - x1) / image_width,
                            h=(y2 - y1) / image_height,
                        ),
                        tracker_id=None,
                    )
                )

        return detections

    def unload(self) -> None:
        self.model = None
