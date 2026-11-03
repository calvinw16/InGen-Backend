"""Convert post-NMS YOLO results into the Week-2 Detection contract."""

from math import isfinite
from typing import Any
from uuid import uuid4

from app.models.perception import BoundingBox, Detection

# Ultralytics' contiguous COCO indices, not the sparse COCO annotation IDs.
COCO_NAMES = [
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
]
COCO_TO_INGEN = {
    index: (
        "person"
        if index == 0
        else (
            "bicycle"
            if index == 1
            else (
                "vehicle"
                if 2 <= index <= 8
                else "animal" if 14 <= index <= 23 else "obstacle"
            )
        )
    )
    for index in range(80)
}


def map_yolo_results(
    results: list[Any], confidence_threshold: float = 0.25
) -> list[Detection]:
    """Map pixel xyxy boxes; skip invalid/degenerate rows and return [] if empty.

    Ultralytics owns decoding, letterbox reversal and NMS. Its orig_shape and
    xyxy are in original image coordinates. Keep confidence strictly above the
    threshold, matching Ultralytics NMS semantics.
    """
    if not isfinite(confidence_threshold) or not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence_threshold must be finite and between 0 and 1")
    detections: list[Detection] = []
    for result in results:
        height, width = result.orig_shape
        if not all(isfinite(v) and v > 0 for v in (height, width)):
            raise RuntimeError("Model returned invalid original image dimensions")
        if result.boxes is None:
            continue
        for box in result.boxes:
            confidence = float(box.conf[0])
            if not isfinite(confidence) or not confidence_threshold < confidence <= 1:
                continue
            coords = box.xyxy[0].tolist()
            if len(coords) != 4 or not all(isfinite(v) for v in coords):
                continue
            x1, y1, x2, y2 = coords
            x1, x2 = (min(max(x, 0), width) for x in (x1, x2))
            y1, y2 = (min(max(y, 0), height) for y in (y1, y2))
            if x2 <= x1 or y2 <= y1:
                continue
            raw_class = float(box.cls[0])
            label = "unknown"
            if isfinite(raw_class) and raw_class.is_integer():
                class_id = int(raw_class)
                # A custom model must not silently inherit COCO index meanings.
                if (
                    0 <= class_id < len(COCO_NAMES)
                    and result.names.get(class_id) == COCO_NAMES[class_id]
                ):
                    label = COCO_TO_INGEN[class_id]
            detections.append(
                Detection(
                    id=str(uuid4()),
                    frame_id="pending",  # Frame processing attaches the real ID.
                    class_label=label,
                    confidence=confidence,
                    bbox=BoundingBox(
                        x=x1 / width,
                        y=y1 / height,
                        w=(x2 - x1) / width,
                        h=(y2 - y1) / height,
                    ),
                    tracker_id=None,
                )
            )
    return detections
