"""Platform policy hook. Raw images are never archived by this service."""

from dataclasses import dataclass

from app.core.config import Settings, settings


@dataclass(frozen=True)
class RetentionPolicy:
    frame_seconds: float
    history_seconds: float
    raw_image_seconds: int = 0


def retention_policy(platform: str, config: Settings = settings) -> RetentionPolicy:
    if platform.casefold() == "fari":
        return RetentionPolicy(
            config.fari_frame_retention_seconds, config.fari_state_history_seconds
        )
    return RetentionPolicy(config.frame_retention_seconds, config.state_history_seconds)
