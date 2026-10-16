import asyncio
from contextlib import suppress

from app.core.config import settings
from app.services.detector import Detector
from app.workers.models import InferenceJob


class WorkerNotReadyError(RuntimeError):
    pass


class QueueFullError(RuntimeError):
    pass


class DetectionWorker:
    def __init__(self, detector: Detector) -> None:
        self.detector = detector

        self.queue: asyncio.Queue[InferenceJob] = asyncio.Queue(
            maxsize=settings.inference_queue_depth
        )

        self.ready = False
        self.healthy = True
        self.running = False

        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.ready = False
        self.healthy = True

        try:
            self.detector.load()
            self.detector.warm_up()
        except Exception:
            self.healthy = False
            raise

        self.running = True
        self.ready = True

        self._task = asyncio.create_task(self._run())

    async def enqueue(
        self,
        job: InferenceJob,
    ) -> None:
        if not self.ready or not self.healthy:
            raise WorkerNotReadyError("Inference worker is not ready.")

        if self.queue.full():
            raise QueueFullError("Inference queue is full.")

        self.queue.put_nowait(job)

    async def _run(self) -> None:
        while self.running or not self.queue.empty():
            try:
                job = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=0.1,
                )
            except TimeoutError:
                continue

            try:
                await self._process_job(job)
            finally:
                self.queue.task_done()

    async def _process_job(
        self,
        job: InferenceJob,
    ) -> None:
        try:
            detections = await asyncio.wait_for(
                asyncio.to_thread(
                    self.detector.predict,
                    job.image,
                ),
                timeout=settings.inference_timeout_seconds,
            )

            await job.on_completed(
                job.frame_id,
                detections,
            )

        except TimeoutError:
            self.healthy = False

            await job.on_failed(
                job.frame_id,
                "INFERENCE_TIMEOUT",
            )

        except RuntimeError:
            self.healthy = False

            await job.on_failed(
                job.frame_id,
                "INFERENCE_FAILED",
            )

    async def stop(self) -> None:
        self.ready = False
        self.running = False

        await self.queue.join()

        if self._task is not None:
            with suppress(asyncio.CancelledError):
                await self._task

        self.detector.unload()
