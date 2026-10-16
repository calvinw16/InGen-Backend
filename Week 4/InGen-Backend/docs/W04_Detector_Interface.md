# Week 3 - Detector Interface

## Purpose

The perception service defines a narrow detector contract so inference implementations can be replaced without changing the API or worker logic.

The `Detector` interface exposes:

- `load()`
- `warm_up()`
- `predict(image) -> list[Detection]`
- `unload()`

The active detector implementation is selected through application configuration rather than hardcoded imports in the API.

## Implementations

### StubDetector

`StubDetector` returns deterministic detection fixtures.

It is used for:

- unit and API testing
- CI execution
- development when model weights or GPU resources are unavailable

The stub allows tests to validate the inference pipeline without downloading YOLO weights or requiring hardware acceleration.

### YoloDetector

`YoloDetector` uses Ultralytics YOLO with pretrained weights.

It:

1. Loads the model once.
2. Performs warm-up inference.
3. Processes images through YOLO.
4. Converts YOLO output into the service's `Detection` schema.
5. Converts pixel bounding boxes into normalized `x/y/w/h` coordinates.

The detector does not manage queues, HTTP requests, readiness state, or retries. Those responsibilities belong to `DetectionWorker`.

## Configuration

Example:

DETECTOR_BACKEND=stub
YOLO_MODEL=yolo11n.pt

The same worker code can therefore operate with either detector implementation.