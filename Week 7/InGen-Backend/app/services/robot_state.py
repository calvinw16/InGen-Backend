"""Thread-safe, in-memory temporal association; intentionally not a full tracker."""

from collections import Counter, deque
from collections.abc import Callable
from datetime import UTC, datetime
from math import hypot
from threading import RLock
from uuid import uuid4

from app.core.config import Settings, settings
from app.models.perception import Detection, RobotState, TrackedEntity
from app.services.retention import retention_policy


class RobotStateEncoder:
    def __init__(self, config: Settings = settings) -> None:
        self.config = config
        self._states: dict[str, RobotState] = {}
        self._lock = RLock()
        self._history: dict[str, deque[RobotState]] = {}

    def restore(self, versions: dict[str, int], snapshots: list[RobotState]) -> None:
        """Restore completed-frame snapshots before the single writer starts."""
        with self._lock:
            self._states.clear()
            self._history.clear()
            for snapshot in snapshots:
                if (
                    self._states.get(snapshot.robot_id, snapshot).platform
                    != snapshot.platform
                ):
                    self._history.pop(snapshot.robot_id, None)
                self._states[snapshot.robot_id] = snapshot.model_copy(deep=True)
                self._history.setdefault(
                    snapshot.robot_id, deque(maxlen=self.config.state_history_limit)
                ).append(snapshot)
            for robot_id, version in versions.items():
                state = self._states.setdefault(robot_id, RobotState(robot_id=robot_id))
                state.state_version = version

    @staticmethod
    def _time(now: datetime | None) -> datetime:
        now = now or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Observation time must include a timezone")
        return now.astimezone(UTC)

    def _age(self, state: RobotState, now: datetime) -> bool:
        before = [(e.entity_id, e.stale) for e in state.entities]
        state.entities = [
            e
            for e in state.entities
            if (now - e.last_seen).total_seconds() < self.config.state_eviction_seconds
        ]
        for entity in state.entities:
            entity.stale = (
                now - entity.last_seen
            ).total_seconds() >= self.config.state_stale_seconds
        return before != [(e.entity_id, e.stale) for e in state.entities]

    def _commit(
        self,
        state: RobotState,
        now: datetime,
        persist: Callable[[RobotState], None] | None = None,
    ) -> None:
        state.entity_count_by_class = dict(
            sorted(Counter(e.class_label for e in state.entities).items())
        )
        state.state_version += 1
        state.updated_at = now
        if persist is not None:
            persist(state)
        if self._states.get(state.robot_id, state).platform != state.platform:
            self._history.pop(state.robot_id, None)
        self._states[state.robot_id] = state
        history = self._history.setdefault(
            state.robot_id, deque(maxlen=self.config.state_history_limit)
        )
        history.append(state.model_copy(deep=True))
        self._prune_history(state.robot_id, now)

    def _prune_history(self, robot_id: str, now: datetime) -> None:
        history = self._history.get(robot_id)
        if history is None:
            return
        while history:
            snapshot = history[0]
            ttl = retention_policy(snapshot.platform, self.config).history_seconds
            if (
                snapshot.updated_at is not None
                and (now - snapshot.updated_at).total_seconds() >= ttl
            ):
                history.popleft()
            else:
                break

    def history(
        self, robot_id: str, limit: int = 20, *, now: datetime | None = None
    ) -> list[RobotState]:
        if not 1 <= limit <= 1000:
            raise ValueError("History limit must be between 1 and 1000")
        with self._lock:
            now = self._time(now)
            self.get(robot_id, now=now)
            self._prune_history(robot_id, now)
            return [
                s.model_copy(deep=True)
                for s in list(self._history.get(robot_id, []))[-limit:]
            ]

    def get(self, robot_id: str, *, now: datetime | None = None) -> RobotState:
        with self._lock:
            now = self._time(now)
            state = self._states.get(robot_id)
            if state is None:
                return RobotState(robot_id=robot_id)
            # Reads age entities too, so idle robots cannot expose live tracks forever.
            now = max(now, state.updated_at or now)
            if self._age(state, now):
                self._commit(state, now)
            self._prune_history(robot_id, now)
            return state.model_copy(deep=True)

    def update(
        self,
        robot_id: str,
        frame_id: str,
        detections: list[Detection],
        *,
        now: datetime | None = None,
        platform: str = "unknown",
        persist: Callable[[RobotState], None] | None = None,
    ) -> RobotState:
        with self._lock:
            now = self._time(now)
            previous = self._states.get(robot_id)
            state = (
                previous.model_copy(deep=True)
                if previous is not None
                else RobotState(robot_id=robot_id)
            )
            if state.updated_at is not None and now < state.updated_at:
                raise ValueError("Observation time cannot move backwards")
            if state.platform != platform:
                state.entities.clear()
            state.platform = platform
            self._age(state, now)
            # Global greedy nearest-pair selection, with stable tie breaking.
            pairs = []
            for index, detection in enumerate(detections):
                box = detection.bbox
                for entity in state.entities:
                    if entity.class_label != detection.class_label:
                        continue
                    old = entity.position
                    distance = hypot(
                        (box.x + box.w / 2) - (old.x + old.w / 2),
                        (box.y + box.h / 2) - (old.y + old.h / 2),
                    )
                    if distance <= self.config.state_association_threshold:
                        pairs.append((distance, entity.entity_id, index, entity))
            used_entities: set[str] = set()
            used_detections: set[int] = set()
            for _, entity_id, index, entity in sorted(pairs, key=lambda p: p[:3]):
                if entity_id in used_entities or index in used_detections:
                    continue
                detection = detections[index]
                entity.position = detection.bbox.model_copy(deep=True)
                entity.confidence = detection.confidence
                entity.last_seen = now
                entity.observation_count += 1
                entity.stale = False
                used_entities.add(entity_id)
                used_detections.add(index)
            for index, detection in enumerate(detections):
                if index not in used_detections:
                    state.entities.append(
                        TrackedEntity(
                            entity_id=str(uuid4()),
                            class_label=detection.class_label,
                            last_seen=now,
                            position=detection.bbox.model_copy(deep=True),
                            confidence=detection.confidence,
                            observation_count=1,
                        )
                    )
            # Hard cap also bounds bursts of unmatched detections within the TTL.
            state.entities.sort(key=lambda e: (e.last_seen, e.entity_id))
            state.entities = state.entities[-self.config.state_max_entities :]
            state.most_recent_frame_id = frame_id
            self._commit(state, now, persist)
            return state.model_copy(deep=True)


robot_states = RobotStateEncoder()
