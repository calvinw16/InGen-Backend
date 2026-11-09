import json
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError
from ultralytics.engine.results import Results

from app.core.config import Settings
from app.services.detection_mapping import COCO_NAMES, map_yolo_results
from app.services.yolo_detector import YoloDetector

FIXTURES = Path(__file__).parent / "fixtures" / "detection_mapping"


def result(rows, image_name="wide.png", names=None):
    with Image.open(FIXTURES / image_name) as image:
        return Results(
            orig_img=np.asarray(image),
            path=image_name,
            names=dict(enumerate(COCO_NAMES)) if names is None else names,
            boxes=np.array(rows, dtype=np.float64).reshape(-1, 6),
        )


def test_fixed_image_and_expected_outputs():
    fixture = json.loads((FIXTURES / "wide.json").read_text())
    detections = map_yolo_results([result(fixture["rows"])])
    actual = [
        d.model_dump(include={"class_label", "confidence", "bbox"}) for d in detections
    ]
    assert actual == fixture["expected"]
    assert len({d.id for d in detections}) == 2
    assert all(d.frame_id == "pending" and d.tracker_id is None for d in detections)


@pytest.mark.parametrize("class_id", range(80))
def test_every_coco_class(class_id):
    expected = (
        "person"
        if class_id == 0
        else (
            "bicycle"
            if class_id == 1
            else (
                "vehicle"
                if class_id in {2, 3, 4, 5, 6, 7, 8}
                else (
                    "animal"
                    if class_id in {14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
                    else "obstacle"
                )
            )
        )
    )
    assert (
        map_yolo_results([result([[0, 0, 20, 20, 0.9, class_id]])])[0].class_label
        == expected
    )


@pytest.mark.parametrize(
    "class_id,names", [(999, {}), (-1, {}), (0, {0: "custom"}), (1.5, {})]
)
def test_unknown_classes(class_id, names):
    assert (
        map_yolo_results([result([[0, 0, 20, 20, 0.9, class_id]], names=names)])[
            0
        ].class_label
        == "unknown"
    )


@pytest.mark.parametrize(
    "rows", [[], [[0, 0, 10, 10, 0.1, 0]], [[0, 0, 10, 10, 0.25, 0]]]
)
def test_empty_detections(rows):
    assert map_yolo_results([result(rows, "empty.png")]) == []
    assert map_yolo_results([]) == []
    no_boxes = result([])
    no_boxes.boxes = None
    assert map_yolo_results([no_boxes]) == []


@pytest.mark.parametrize(
    "row",
    [
        [10, 0, 5, 10, 0.9, 0],
        [0, 0, 0, 10, 0.9, 0],
        [201, 0, 220, 10, 0.9, 0],
        [0, 0, float("nan"), 10, 0.9, 0],
        [0, 0, 10, 10, float("inf"), 0],
        [0, 0, 10, 10, 1.1, 0],
    ],
)
def test_invalid_boxes_are_skipped(row):
    assert map_yolo_results([result([row])]) == []


def test_portrait_uses_original_dimensions():
    detection = map_yolo_results([result([[8, 32, 40, 112, 0.9, 0]], "empty.png")])[0]
    assert detection.bbox.model_dump() == {"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.5}


def test_predict_and_warmup_use_explicit_nms_settings():
    detector = YoloDetector(
        confidence_threshold=0.6, nms_iou_threshold=0.4, max_detections=10
    )
    detector.model = Mock()
    detector.model.predict.return_value = [result([[0, 0, 20, 20, 0.5, 0]])]
    with Image.open(FIXTURES / "wide.png") as image:
        assert detector.predict(image) == []
    detector.warm_up()
    for call in detector.model.predict.call_args_list:
        assert {k: v for k, v in call.kwargs.items() if k != "source"} == {
            "verbose": False,
            "conf": 0.6,
            "iou": 0.4,
            "agnostic_nms": False,
            "max_det": 10,
        }


@pytest.mark.parametrize(
    "field,value",
    [
        ("yolo_confidence_threshold", -0.1),
        ("yolo_confidence_threshold", float("nan")),
        ("yolo_nms_iou_threshold", 1.1),
        ("yolo_max_detections", 0),
    ],
)
def test_invalid_settings(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_factory_passes_settings(monkeypatch):
    from app.services import detector_factory

    monkeypatch.setattr(detector_factory.settings, "detector_backend", "yolo")
    monkeypatch.setattr(detector_factory.settings, "yolo_confidence_threshold", 0.6)
    detector = detector_factory.create_detector()
    assert detector.options.confidence_threshold == 0.6
