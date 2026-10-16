## Work Completed

- Implemented the `Detector` interface for interchangeable inference backends.
- Added `StubDetector` for deterministic CI and API testing.
- Added `YoloDetector` using Ultralytics YOLO.
- Implemented `DetectionWorker` to manage detector lifecycle and inference execution.
- Added model loading and dummy warm-up during startup.
- Connected `/readyz` to the worker's actual readiness and health state.
- Added a bounded inference queue with a maximum depth of 4.
- Added HTTP 503 overload behavior with `Retry-After`.
- Added a 2-second inference timeout.
- Added graceful shutdown that drains accepted work before unloading the detector.
- Added async worker tests for startup, processing, queue behavior, failures, timeouts, and shutdown.
- Fixed a duplicate worker-instance bug that caused the API to observe incorrect readiness state.
- Ran Black, Ruff, mypy, and pytest coverage checks.

## Technical Decisions

- Queue depth: 4 pending frames.
- Inference timeout: 2.0 seconds.
- Retry-After value: 1 second.
- Detector implementation is selected through configuration.
- Stub inference is used in CI to avoid downloading model weights.
- A single shared worker instance is used across API and health endpoints.

## Current Limitations

- Inference is logically decoupled from the API but is not yet running in a fully separate process.
- PostgreSQL persistence is not yet integrated.
- YOLO performance has not yet been benchmarked on target hardware.