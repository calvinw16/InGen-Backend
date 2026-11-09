"""Generate synthetic telemetry into a migrated development database."""

import argparse
import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.models import telemetry as db
from app.models.perception import BoundingBox, Detection
from app.services.retention import retention_policy
from app.services.robot_state import RobotStateEncoder
from app.services.telemetry_store import engine


def seed(
    days: int, robots: int, per_day: int, anchor: datetime, seed_value: int = 7
) -> dict:
    rng = random.Random(seed_value)
    prefix = "seed-" + uuid4().hex[:8]
    now = datetime.now(UTC)
    total = 0
    with engine().begin() as conn:
        for robot in range(robots):
            robot_id = f"{prefix}-{robot:02}"
            platform = "fari" if robot % 3 == 2 else "aido"
            policy = retention_policy(platform)
            encoder = RobotStateEncoder()
            frame_rows, detection_rows, snapshot_rows, event_rows = [], [], [], []
            for i in range(days * per_day):
                day, slot = divmod(i, per_day)
                captured = anchor - timedelta(
                    days=days - day, seconds=-slot * 86400 / per_day
                )
                received = captured + timedelta(milliseconds=rng.randint(15, 250))
                frame_id = str(uuid4())
                frame_rows.append(
                    {
                        "id": frame_id,
                        "robot_id": robot_id,
                        "platform": platform,
                        "captured_at": captured,
                        "received_at": received,
                        "width": 1280,
                        "height": 720,
                        "format": "jpeg",
                        "size_bytes": rng.randint(28_000, 190_000),
                        "checksum": hashlib.sha256(frame_id.encode()).hexdigest(),
                        "job_id": str(uuid4()),
                        "status": "completed",
                        "expires_at": now + timedelta(seconds=policy.frame_seconds),
                    }
                )
                labels = (
                    ("person", "person", "obstacle", "animal")
                    if platform == "fari"
                    else (
                        "person",
                        "vehicle",
                        "vehicle",
                        "bicycle",
                        "obstacle",
                        "animal",
                    )
                )
                detected = []
                for _ in range(
                    rng.choices((0, 1, 2, 3, 5), weights=(9, 30, 35, 20, 6))[0]
                ):
                    item = Detection(
                        id=str(uuid4()),
                        frame_id=frame_id,
                        class_label=rng.choice(labels),
                        confidence=round(rng.uniform(0.3, 0.99), 3),
                        bbox=BoundingBox(
                            x=rng.uniform(0.02, 0.75),
                            y=rng.uniform(0.02, 0.75),
                            w=rng.uniform(0.05, 0.2),
                            h=rng.uniform(0.05, 0.2),
                        ),
                    )
                    detected.append(item)
                    detection_rows.append(
                        dict(
                            id=item.id,
                            frame_id=frame_id,
                            robot_id=robot_id,
                            captured_at=captured,
                            class_label=item.class_label,
                            confidence=item.confidence,
                            tracker_id=None,
                            **item.bbox.model_dump(),
                        )
                    )
                event_rows.append(
                    {
                        "id": str(uuid4()),
                        "frame_id": frame_id,
                        "kind": "frame_completed",
                        "occurred_at": received,
                        "payload": {"synthetic": True},
                    }
                )
                if i >= days * per_day - 20:
                    # Represent a small recent burst for the state/history dashboard.
                    observed = now - timedelta(seconds=(days * per_day - 1 - i) / 4)
                    state = encoder.update(
                        robot_id, frame_id, detected, platform=platform, now=observed
                    )
                    snapshot_rows.append(
                        {
                            "robot_id": robot_id,
                            "version": state.state_version,
                            "platform": platform,
                            "created_at": observed,
                            "expires_at": now
                            + timedelta(seconds=policy.history_seconds),
                            "payload": state.model_dump(mode="json"),
                        }
                    )
            conn.execute(
                db.robots.insert().values(
                    id=robot_id,
                    platform=platform,
                    latest_capture=frame_rows[-1]["captured_at"],
                    state_version=snapshot_rows[-1]["version"],
                )
            )
            conn.execute(db.frames.insert(), frame_rows)
            if detection_rows:
                conn.execute(db.detections.insert(), detection_rows)
            conn.execute(db.events.insert(), event_rows)
            conn.execute(db.snapshots.insert(), snapshot_rows)
            total += len(detection_rows)
    return {
        "prefix": prefix,
        "days": days,
        "robots": robots,
        "frames": days * robots * per_day,
        "detections": total,
        "anchor": anchor.isoformat(),
        "seed": seed_value,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--robots", type=int, default=6)
    parser.add_argument("--frames-per-day", type=int, default=240)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--anchor", type=datetime.fromisoformat, default=datetime.now(UTC)
    )
    args = parser.parse_args()
    if (
        min(args.days, args.robots, args.frames_per_day) < 1
        or args.anchor.utcoffset() is None
        or args.anchor > datetime.now(UTC)
    ):
        parser.error(
            "Counts must be positive and anchor must be timezone-aware and not in the future."
        )
    print(
        json.dumps(
            seed(args.days, args.robots, args.frames_per_day, args.anchor, args.seed)
        )
    )


if __name__ == "__main__":
    main()
