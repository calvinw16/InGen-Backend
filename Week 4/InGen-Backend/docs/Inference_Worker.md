# Inference Worker Configuration

## Queue Depth

The inference queue has a maximum depth of 4 pending frames.

A small bounded queue allows the service to absorb short request bursts
without allowing stale perception frames to accumulate indefinitely.
When the queue reaches capacity, new inference requests are rejected
with HTTP 503 Service Unavailable and a Retry-After header.

## Inference Timeout

Each inference job has a 2.0 second timeout.

The service targets normal inference completion substantially below this
limit. The 2-second timeout allows temporary processing variation while
preventing a stalled inference request from being treated as healthy
indefinitely.

When an inference timeout occurs, the affected frame is marked as failed
and the worker is marked unhealthy. The readiness endpoint then returns
HTTP 503 until the worker is recovered or restarted.

## Model Lifecycle

The configured detector is loaded once during service startup and warmed
using a dummy inference before the worker is marked ready.

The `/readyz` endpoint returns not-ready until loading and warm-up have
completed successfully.

During shutdown, the worker stops accepting new jobs, drains queued and
in-flight work, unloads the detector, and exits.