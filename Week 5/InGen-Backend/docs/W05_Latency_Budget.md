# Week 5 latency budget and measurements

## Result and Week-1 baseline

**The local service met the Week-1 p95 ≤ 1,000 ms target in all four measured
cases. Full robot-to-backend network latency remains unverified.** All 400
measured frames completed; none were rejected, timed out, or failed.

Source: `Week 1/InGen-Backend/docs/W01_Service_Design_Doc.docx`, section
“Proposed Engineering Targets”: “p95 latency target of 1 second”. The same
section proposes 2 frames/second. The earlier latency-budget section includes
network transmission, API processing, queue waiting, model inference and result
delivery. This run covers local HTTP submission through completed result
retrieval, not physical network transmission. The 2-second worker timeout is a
failure limit, not the performance target.

## Measured end-to-end latency

All values are milliseconds. Each case has 100 measured frames after three
excluded warm-up frames, plus the detector's startup warm-up.

| Input resolution | Submission batch | p50 | p95 | p99 | p95 target | Local target met | Failures |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| 640x480 | 1 | 38.607 | 55.078 | 80.783 | 1,000 | Yes | 0 |
| 640x480 | 4 | 112.875 | 196.842 | 286.037 | 1,000 | Yes | 0 |
| 1280x720 | 1 | 33.739 | 40.889 | 56.468 | 1,000 | Yes | 0 |
| 1280x720 | 4 | 117.656 | 184.272 | 222.831 | 1,000 | Yes | 0 |

## Measured stage decomposition

Each cell is **p50 / p95 / p99**, in milliseconds. Per-stage percentiles do not
add up to the end-to-end percentile: each stage can have a different slowest
frame. Raw samples preserve the per-frame additive decomposition.

| Input / batch | Decode | Inference | Serialization | Queue | Other |
| --- | ---: | ---: | ---: | ---: | ---: |
| 640x480 / 1 | 1.040 / 1.423 / 1.713 | 35.399 / 50.411 / 76.810 | 0.017 / 0.027 / 0.101 | 0.073 / 0.360 / 0.471 | 2.017 / 3.382 / 3.793 |
| 640x480 / 4 | 0.964 / 1.118 / 1.138 | 35.511 / 56.522 / 87.694 | 0.015 / 0.022 / 0.029 | 71.209 / 158.204 / 244.952 | 5.457 / 6.616 / 7.161 |
| 1280x720 / 1 | 2.630 / 2.953 / 3.091 | 28.867 / 35.973 / 51.393 | 0.014 / 0.020 / 0.041 | 0.137 / 0.301 / 0.331 | 2.161 / 3.138 / 4.189 |
| 1280x720 / 4 | 2.756 / 3.102 / 3.456 | 36.202 / 51.623 / 92.289 | 0.017 / 0.027 / 0.054 | 69.529 / 136.991 / 165.839 | 10.231 / 13.212 / 15.605 |

## Measurement boundaries

- End-to-end: client monotonic clock immediately before POST `/v1/frames`
  through receipt and JSON parsing of the first completed GET response. A 202
  acknowledgement alone is not completion. Includes client JSON submission,
  service processing, queue wait, result polling and response handling.
- Decode: API payload-length check, base64 validation/decode, JPEG format
  validation, Pillow pixel decoding and image copy. Request JSON parsing and
  Pydantic request validation occur before this timer.
- Inference: worker wall time around `asyncio.to_thread(detector.predict)`;
  includes thread dispatch, model preprocessing, forward pass, NMS, mapping,
  and return to the event loop. It is not GPU kernel time.
- Serialization: actual completed GET response `model_dump_json()` time,
  measured once for that response, not an extra synthetic serialization pass.
  Instrumented GETs return that same serialized body. UTF-8 response encoding,
  headers, middleware, earlier poll responses and client parsing are in Other.
- Queue: enqueue to worker starting the inference wait.
- Other: per-frame end-to-end minus the four measured stages. Includes request
  validation, metadata, callbacks, middleware, scheduling and polling overhead.

Timing uses `perf_counter()`. `LATENCY_METRICS_ENABLED=true` exposes stage
values as `X-Latency-decode_ms`, `X-Latency-inference_ms`,
`X-Latency-serialization_ms`, and `X-Latency-queue_ms` headers on frame GETs.
Metrics are disabled by default and never enter the JSON schema. Incomplete
frames do not yet have inference timing. The benchmark requires completion
before reading all stage headers. Failed requests are counted and retained,
not converted into successful latency samples. A case passes only if every
measured frame succeeds and its p95 meets the configured target.

## Environment and limitations

Measured at 2026-10-27T20:18:04.658412+00:00 on macOS-15.6.1-arm64-arm-64bit, Python 3.12.7.
YOLO11n pretrained COCO weights, device `cpu`; Ultralytics 8.4.177, PyTorch 2.14.1, FastAPI 0.141.1, Pillow 12.3.0.
The sandbox did not expose the CPU model or RAM size. Weight and input-image
SHA-256 digests are recorded in the raw report.

The input is the installed Ultralytics `assets/bus.jpg`, resized to each target
resolution and encoded as JPEG quality 85 before timing. Each case repeats
that image; this is a reproducible microbenchmark, not a representative video
corpus or accuracy evaluation. The network input uses the model's default
640-pixel size with aspect-ratio-aware preprocessing; larger source images do
not imply a larger model tensor. This helps explain why the 720p single-frame
case is faster despite taking longer to decode.

Submission batches are 1 and 4 concurrent POST/poll tasks, with a barrier
between batches. The existing single worker still predicts **one image at a
time**. These are service submission-batch settings, not tensor minibatches;
model batching is not supported by the current detector protocol. The default
queue depth remains 4, inference timeout 2 seconds, confidence 0.25, NMS IoU
0.7, and maximum detections 300. No settings were tuned after seeing results.
The poll interval is 1 ms and client deadline is 15 seconds.

HTTPX ASGI transport executes the real routes, middleware, image decode,
worker queue, YOLO inference, frame store and result serialization. It excludes
TCP, TLS, radio/network delay and deployment proxies. Routine HTTP logging
remained enabled. Development checks ran during part of this measurement;
CPU contention and polling jitter are retained in the numbers rather than
removed. This is one local run, not an isolated production capacity claim.
With 100 samples per case, p99 is particularly sensitive to a few observations.
Percentiles use linear interpolation at `(N - 1) * percentile / 100`.

Queue wait grows substantially at batch four. The measured local p95 headroom
in the slowest case is about 803 ms, but this is not an independently verified
network budget and percentile components must not be added as if correlated.
A deployment run with representative video and actual network conditions is
needed before claiming the full Week-1 end-to-end requirement is satisfied.

## Reproduce

From the repository root, install project and development dependencies with
`uv sync`, then run:

```sh
uv run python -m scripts.benchmark_latency --backend yolo --model yolo11n.pt --image .venv/lib/python3.12/site-packages/ultralytics/assets/bus.jpg --frames 100 --warmup 3 --resolutions 640x480 1280x720 --batches 1 4 --target-ms 1000 --output benchmarks/latency-yolo.json
```

The initial run needed a model-weight download. The successful measured run
used the downloaded file `/tmp/ingen-yolo11n.pt` with the same command's
`--model` option. A normal `yolo11n.pt` invocation downloads weights if needed.
Adjust the installed Python directory in `--image`, or supply a local JPEG.
Use `--backend stub` only for harness checks; stub numbers do not establish
YOLO performance. `--frames` is the number per matrix case; `--batches` accepts
additional sizes, including overload tests. Rejected and failed samples remain
in the report. Warm-up observations are stored separately and excluded from
reported percentiles. The benchmark removes its frame records after use.

[Raw measurements and environment](../benchmarks/latency-yolo.json) contain all
400 samples, warm-ups, failure counts, percentile summaries and configuration.
The instrumentation and percentile calculation have automated regression tests.
