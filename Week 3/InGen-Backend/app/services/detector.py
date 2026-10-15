#use protocol to define an interface that other classes can follow
#Allows for YOLO model to be swappable to any detection model to be used as type detector
from typing import Protocol

from PIL.Image import Image

from app.models.perception import Detection


class Detector(Protocol):
    def load(self) -> None:
        """Load detector resources into memory."""
        ...

    def warm_up(self) -> None:
        """Run a warm-up inference so first real request is not unusually slow."""
        ...

    def predict(self, image: Image) -> list[Detection]:
        """Run object detection on one image."""
        ...

    def unload(self) -> None:
        """Release detector resources."""
        ...