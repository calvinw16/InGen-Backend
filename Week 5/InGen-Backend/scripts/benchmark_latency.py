"""Run real HTTP API paths in-process, including asynchronous completion polling.

Usage: python -m scripts.benchmark_latency --backend yolo --frames 100
"""

import argparse
import asyncio
import base64
import hashlib
import json
import platform
from datetime import UTC, datetime
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from time import perf_counter

import httpx
from PIL import Image

METRICS = (
    "end_to_end_ms",
    "decode_ms",
    "inference_ms",
    "serialization_ms",
    "queue_ms",
    "other_ms",
)


def percentiles(values):
    """Linear interpolation, equivalent to numpy's default percentile method."""
    ordered = sorted(values)
    if not ordered:
        return None
    result = {}
    for percentile in (50, 95, 99):
        index = (len(ordered) - 1) * percentile / 100
        lower = int(index)
        upper = min(lower + 1, len(ordered) - 1)
        result[f"p{percentile}"] = ordered[lower] + (
            ordered[upper] - ordered[lower]
        ) * (index - lower)
    return result


async def run(args):
    # Configure before importing app/runtime, which construct the singleton worker.
    from app.core.config import settings

    settings.detector_backend = args.backend
    settings.yolo_model = args.model
    settings.latency_metrics_enabled = True
    from app.main import app
    from app.services.frame_store import frames

    source = Image.open(args.image).convert("RGB")
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "versions": {
            name: version(name)
            for name in ("ultralytics", "torch", "fastapi", "pillow")
        },
        "backend": args.backend,
        "model": args.model,
        "image": str(args.image),
        "image_sha256": hashlib.sha256(args.image.read_bytes()).hexdigest(),
        "frames_per_case": args.frames,
        "warmup_frames_per_case": args.warmup,
        "batch_semantics": "concurrent HTTP submissions; single-frame worker inference",
        "transport": "in-process HTTP ASGI; no physical network",
        "poll_interval_ms": args.poll_ms,
        "target": {"percentile": "p95", "ms": args.target_ms},
        "settings": settings.model_dump(
            include={
                "inference_queue_depth",
                "inference_timeout_seconds",
                "yolo_confidence_threshold",
                "yolo_nms_iou_threshold",
                "yolo_max_detections",
            }
        ),
        "cases": [],
    }
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://benchmark"
        ) as client,
    ):
        from app.core.runtime import worker

        if args.backend == "yolo":
            report["device"] = str(worker.detector.model.predictor.device)
            report["model_input_size"] = worker.detector.model.predictor.imgsz
            report["weights_sha256"] = (
                hashlib.sha256(Path(args.model).read_bytes()).hexdigest()
                if Path(args.model).is_file()
                else None
            )
        for resolution in args.resolutions:
            width, height = map(int, resolution.split("x"))
            buffer = BytesIO()
            source.resize((width, height)).save(buffer, format="JPEG", quality=85)
            encoded = base64.b64encode(buffer.getvalue()).decode()
            for batch in args.batches:

                async def measure(encoded=encoded):
                    frame_id = None
                    start = perf_counter()
                    try:
                        response = await client.post(
                            "/v1/frames",
                            json={
                                "robot_id": "benchmark",
                                "platform": "benchmark",
                                "timestamp": datetime.now(UTC).isoformat(),
                                "image_base64": encoded,
                            },
                        )
                        if response.status_code != 202:
                            return {
                                "error": f"submit HTTP {response.status_code}",
                                "elapsed_ms": (perf_counter() - start) * 1000,
                            }
                        frame_id = response.json()["frame_id"]
                        while perf_counter() - start < args.deadline:
                            response = await client.get(f"/v1/frames/{frame_id}")
                            response.raise_for_status()
                            status = response.json()["status"]
                            if status == "failed":
                                return {
                                    "error": "inference failed",
                                    "elapsed_ms": (perf_counter() - start) * 1000,
                                }
                            if status == "completed":
                                elapsed = (perf_counter() - start) * 1000
                                stages = {
                                    key: float(response.headers[f"X-Latency-{key}"])
                                    for key in METRICS[1:5]
                                }
                                return {
                                    "end_to_end_ms": elapsed,
                                    **stages,
                                    "other_ms": elapsed - sum(stages.values()),
                                }
                            await asyncio.sleep(args.poll_ms / 1000)
                        return {
                            "error": "client deadline exceeded",
                            "elapsed_ms": (perf_counter() - start) * 1000,
                        }
                    finally:
                        if frame_id is not None:
                            frames.pop(frame_id, None)

                warmup = [await measure() for _ in range(args.warmup)]
                samples = []
                for offset in range(0, args.frames, batch):
                    samples.extend(
                        await asyncio.gather(
                            *(
                                measure()
                                for _ in range(min(batch, args.frames - offset))
                            )
                        )
                    )
                successes = [sample for sample in samples if "error" not in sample]
                summary = {
                    key: percentiles([sample[key] for sample in successes])
                    for key in METRICS
                }
                passed = (
                    len(successes) == args.frames
                    and summary["end_to_end_ms"]["p95"] <= args.target_ms
                )
                case = {
                    "resolution": resolution,
                    "submission_batch": batch,
                    "jpeg_bytes": len(buffer.getvalue()),
                    "successful": len(successes),
                    "failed": args.frames - len(successes),
                    "target_met": passed,
                    "summary": summary,
                    "warmup": warmup,
                    "samples": samples,
                }
                report["cases"].append(case)
                print(
                    f"{resolution} batch={batch}: {len(successes)}/{args.frames} completed, percentiles_ms={summary['end_to_end_ms']}, target_met={passed}",
                    flush=True,
                )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("stub", "yolo"), default="yolo")
    parser.add_argument("--model", default="yolo11n.pt")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--resolutions", nargs="+", default=["640x480", "1280x720"])
    parser.add_argument("--batches", nargs="+", type=int, default=[1, 4])
    parser.add_argument("--poll-ms", type=float, default=1)
    parser.add_argument("--deadline", type=float, default=15)
    parser.add_argument("--target-ms", type=float, default=1000)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/latency.json"))
    args = parser.parse_args()
    if (
        args.frames < 1
        or args.warmup < 0
        or min(args.batches) < 1
        or args.poll_ms <= 0
        or args.deadline <= 0
        or args.target_ms <= 0
    ):
        parser.error(
            "frames, batches and timing values must be positive; warmup must be nonnegative"
        )
    for resolution in args.resolutions:
        try:
            width, height = map(int, resolution.split("x"))
            if min(width, height) < 1:
                raise ValueError
        except ValueError:
            parser.error("resolutions must be positive WIDTHxHEIGHT values")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
