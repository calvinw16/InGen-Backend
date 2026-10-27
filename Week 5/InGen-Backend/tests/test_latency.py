import time
from datetime import UTC, datetime

import pytest

from app.core.config import settings
from scripts.benchmark_latency import percentiles
from tests.test_v1 import create_test_image


def test_percentiles_interpolate_and_handle_small_samples():
    assert percentiles([]) is None
    assert percentiles([5]) == {"p50": 5, "p95": 5, "p99": 5}
    assert percentiles([100, 0]) == {"p50": 50, "p95": 95, "p99": 99}


@pytest.mark.parametrize("enabled", [False, True])
def test_completed_frame_timings(client, monkeypatch, enabled):
    from app.core.runtime import worker

    original = worker.detector.predict

    def delayed_predict(image):
        time.sleep(0.02)
        return original(image)

    monkeypatch.setattr(worker.detector, "predict", delayed_predict)
    monkeypatch.setattr(settings, "latency_metrics_enabled", enabled)
    submitted = client.post(
        "/v1/frames",
        json={
            "robot_id": "timing_test",
            "platform": "test",
            "timestamp": datetime.now(UTC).isoformat(),
            "image_base64": create_test_image(),
        },
    )
    assert submitted.status_code == 202
    frame_id = submitted.json()["frame_id"]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(f"/v1/frames/{frame_id}")
        if response.json()["status"] == "completed":
            break
        time.sleep(0.001)
    assert response.json()["status"] == "completed"
    assert response.json()["detections"][0]["frame_id"] == frame_id
    assert set(response.json()) == {"frame", "job_id", "status", "detections"}
    if enabled:
        for metric in ("decode_ms", "queue_ms", "inference_ms", "serialization_ms"):
            assert float(response.headers[f"X-Latency-{metric}"]) >= 0
        assert float(response.headers["X-Latency-inference_ms"]) >= 20
    else:
        assert not any(key.startswith("x-latency-") for key in response.headers)
