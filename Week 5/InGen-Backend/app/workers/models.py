from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from PIL.Image import Image

from app.models.perception import Detection

CompletionCallback = Callable[
    [str, list[Detection]],
    Awaitable[None],
]

FailureCallback = Callable[
    [str, str],
    Awaitable[None],
]


@dataclass
class InferenceJob:
    frame_id: str
    image: Image
    on_completed: CompletionCallback
    on_failed: FailureCallback
    timings: dict[str, float] = field(default_factory=dict)
    enqueued_at: float | None = None
