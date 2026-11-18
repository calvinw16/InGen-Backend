import pytest
from PIL import Image

from app.services.stub_detector import StubDetector


# TEST to ensure load model is required
def test_stub_detector_requires_load():
    detector = StubDetector()

    image = Image.new(
        "RGB",
        (640, 480),
        "white",
    )
    # Check that expected exception occurs
    with pytest.raises(RuntimeError):
        detector.predict(image)


# TEST inference model returns deterministic detection
def test_stub_detector_returns_deterministic_detection():
    detector = StubDetector()
    detector.load()
    detector.warm_up()

    image = Image.new(
        "RGB",
        (640, 480),
        "white",
    )

    detections = detector.predict(image)

    assert len(detections) == 1
    assert detections[0].class_label == "person"
    assert detections[0].confidence == 0.95


# TEST inference model properly unloads
def test_stub_detector_unload():
    detector = StubDetector()
    detector.load()
    detector.unload()

    image = Image.new(
        "RGB",
        (640, 480),
        "white",
    )

    with pytest.raises(RuntimeError):
        detector.predict(image)
