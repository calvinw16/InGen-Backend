# Week 3 - Inference Worker Design

## Overview

The perception backend uses a shared `DetectionWorker` to manage inference execution. The worker is responsible for detector lifecycle, readiness and health state, queue management, timeout handling, and graceful shutdown.

The worker does not implement object detection itself. Instead, it depends on the `Detector` interface, which can be backed by either `StubDetector` or `YoloDetector`.

## Architecture

Robot / Client
    |
    v
FastAPI
    |
    v
DetectionWorker
    |
    v
Bounded Inference Queue
    |
    v
Detector Interface
    |
    +-- StubDetector
    |
    +-- YoloDetector

The API and health endpoints reference the same shared worker instance so they observe the same readiness and health state.

## Detector Lifecycle

The configured detector is loaded once during application startup.

Startup sequence:

1. Create the detector from configuration.
2. Call `load()`.
3. Call `warm_up()` using a dummy inference.
4. Mark the worker as ready.
5. Begin accepting inference jobs.

The warm-up step ensures that the first real request does not pay model initialization or warm-up cost.

During shutdown, the worker stops accepting new work, drains queued jobs, waits for in-flight jobs to finish, and calls `unload()` on the detector.

## Readiness and Health

The worker tracks two primary states:

- `ready`: the detector has successfully loaded and completed warm-up.
- `healthy`: the worker has not experienced an inference failure or timeout that requires recovery.

The `/healthz` endpoint reports whether the API process is alive.

The `/readyz` endpoint returns HTTP 200 only when the inference worker is both ready and healthy. Otherwise it returns HTTP 503.

## Queue Policy

The inference queue has a maximum depth of 4 pending jobs.

A bounded queue prevents an unbounded backlog of perception frames. Robot perception data becomes stale quickly, so the service rejects excess work instead of allowing old frames to accumulate indefinitely.

When the queue is full, new inference requests are rejected with:

- HTTP 503 Service Unavailable
- `Retry-After: 1`

The client may retry after the specified delay.

## Inference Timeout

Each inference request has a timeout of 2.0 seconds.

The normal performance target is substantially lower than this value. The 2-second timeout allows temporary processing variation while preventing a stalled inference request from remaining active indefinitely.

When a timeout occurs:

1. The current inference job is marked failed.
2. The error code is recorded as `INFERENCE_TIMEOUT`.
3. The worker is marked unhealthy.
4. `/readyz` returns HTTP 503 until the worker is recovered or restarted.

## Failure Handling

If detector prediction raises an expected runtime failure:

1. The affected job is marked failed.
2. The worker is marked unhealthy.
3. The failure is surfaced through the frame-processing state.

Unexpected programming errors are not silently swallowed so they remain visible during development and testing.

## Graceful Shutdown

The worker performs graceful shutdown by:

1. Setting `ready` to false.
2. Refusing new inference jobs.
3. Waiting for all queued work to finish.
4. Waiting for the worker task to exit.
5. Unloading detector resources.

This prevents accepted work from being silently discarded during normal service shutdown.

## Current Limitation

The current `DetectionWorker` is logically separated from the API but still executes within the FastAPI application process, with synchronous detector prediction offloaded through `asyncio.to_thread()`.

The final architecture may move inference into a dedicated process or worker service to provide stronger fault isolation and independent scaling.