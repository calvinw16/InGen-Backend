import asyncio

import pytest
from PIL import Image

from app.core.config import settings
from app.services.stub_detector import StubDetector
from app.workers.detection_worker import (
    DetectionWorker,
    QueueFullError,
)
from app.workers.models import InferenceJob


async def completed_callback(
    frame_id: str,
    detections,
) -> None:
    return None


async def failed_callback(
    frame_id: str,
    error_code: str,
) -> None:
    return None


@pytest.mark.asyncio
async def test_worker_not_ready_before_start():
    worker = DetectionWorker(StubDetector())

    assert worker.ready is False


@pytest.mark.asyncio
async def test_worker_ready_after_start():
    worker = DetectionWorker(StubDetector())

    await worker.start()

    assert worker.ready is True
    assert worker.healthy is True

    await worker.stop()


@pytest.mark.asyncio
async def test_worker_processes_job():
    worker = DetectionWorker(StubDetector())

    results = []

    async def on_completed(
        frame_id,
        detections,
    ):
        results.extend(detections)

    await worker.start()

    image = Image.new(
        "RGB",
        (640, 480),
        "white",
    )

    await worker.enqueue(
        InferenceJob(
            frame_id="frame_001",
            image=image,
            on_completed=on_completed,
            on_failed=failed_callback,
        )
    )

    await worker.queue.join()

    assert len(results) == 1
    assert results[0].class_label == "person"

    await worker.stop()


class CountingDetector:
    def __init__(self):
        self.load_calls = 0
        self.warm_up_calls = 0
        self.unload_calls = 0

    def load(self):
        self.load_calls += 1

    def warm_up(self):
        self.warm_up_calls += 1

    def predict(self, image):
        return []

    def unload(self):
        self.unload_calls += 1


@pytest.mark.asyncio
async def test_worker_loads_and_warms_detector_once():
    detector = CountingDetector()
    worker = DetectionWorker(detector)

    await worker.start()

    assert detector.load_calls == 1
    assert detector.warm_up_calls == 1

    await worker.stop()

    assert detector.unload_calls == 1


class BlockingDetector:
    def load(self):
        pass

    def warm_up(self):
        pass

    def predict(self, image):
        import time

        time.sleep(1)
        return []

    def unload(self):
        pass


@pytest.mark.asyncio
async def test_queue_full_raises_error():
    detector = BlockingDetector()
    worker = DetectionWorker(detector)

    await worker.start()

    image = Image.new(
        "RGB",
        (640, 480),
        "white",
    )

    async def noop_completed(frame_id, detections):
        return None

    async def noop_failed(frame_id, error_code):
        return None

    jobs = []

    for index in range(settings.inference_queue_depth + 1):
        jobs.append(
            InferenceJob(
                frame_id=f"frame_{index}",
                image=image,
                on_completed=noop_completed,
                on_failed=noop_failed,
            )
        )

    # First job starts processing.
    await worker.enqueue(jobs[0])

    # Give the worker a moment to take that job off the queue.
    await asyncio.sleep(0.05)

    # Fill the bounded queue.
    for job in jobs[1 : settings.inference_queue_depth + 1]:
        await worker.enqueue(job)

    # One more job should be rejected.
    extra_job = InferenceJob(
        frame_id="extra_frame",
        image=image,
        on_completed=noop_completed,
        on_failed=noop_failed,
    )

    with pytest.raises(QueueFullError):
        await worker.enqueue(extra_job)

    await worker.stop()


class FailingDetector:
    def load(self):
        pass

    def warm_up(self):
        pass

    def predict(self, image):
        raise RuntimeError("Model failure")

    def unload(self):
        pass


@pytest.mark.asyncio
async def test_inference_failure_marks_job_failed():
    detector = FailingDetector()
    worker = DetectionWorker(detector)

    failed = {}

    async def on_completed(frame_id, detections):
        return None

    async def on_failed(frame_id, error_code):
        failed["frame_id"] = frame_id
        failed["error_code"] = error_code

    await worker.start()

    image = Image.new(
        "RGB",
        (640, 480),
        "white",
    )

    await worker.enqueue(
        InferenceJob(
            frame_id="failed_frame",
            image=image,
            on_completed=on_completed,
            on_failed=on_failed,
        )
    )

    await worker.queue.join()

    assert worker.healthy is False
    assert failed["frame_id"] == "failed_frame"
    assert failed["error_code"] == "INFERENCE_FAILED"

    await worker.stop()


class ShortDelayDetector:
    def load(self):
        pass

    def warm_up(self):
        pass

    def predict(self, image):
        import time

        time.sleep(0.1)
        return []

    def unload(self):
        pass


@pytest.mark.asyncio
async def test_shutdown_drains_queued_work():
    detector = ShortDelayDetector()
    worker = DetectionWorker(detector)

    completed_frames = []

    async def on_completed(frame_id, detections):
        completed_frames.append(frame_id)

    async def on_failed(frame_id, error_code):
        return None

    await worker.start()

    image = Image.new(
        "RGB",
        (640, 480),
        "white",
    )

    for index in range(3):
        await worker.enqueue(
            InferenceJob(
                frame_id=f"frame_{index}",
                image=image,
                on_completed=on_completed,
                on_failed=on_failed,
            )
        )

    await worker.stop()

    assert completed_frames == [
        "frame_0",
        "frame_1",
        "frame_2",
    ]
