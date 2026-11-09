"""Database operations for frame ingestion and retention."""

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from threading import Lock
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.models import telemetry as db
from app.models.perception import Detection, FrameDetailResponse, RobotState
from app.services.retention import retention_policy

log = logging.getLogger(__name__)
_quality: Counter[str] = Counter()
_quality_lock = Lock()


def flag(kind: str) -> None:
    with _quality_lock:
        _quality[kind] += 1


def quality_stats() -> dict[str, int]:
    with _quality_lock:
        return {
            kind: _quality[kind]
            for kind in (
                "future_timestamp",
                "old_timestamp",
                "out_of_order_frame",
                "invalid_bbox",
                "invalid_confidence",
                "duplicate_detection",
            )
        }


def make_engine(url: str) -> sa.Engine:
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = sa.create_engine(url)
    if engine.dialect.name == "sqlite":

        @sa.event.listens_for(engine, "connect")
        def enable_fk(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


@lru_cache(maxsize=4)
def engine_for(url: str) -> sa.Engine:
    return make_engine(url)


def engine() -> sa.Engine:
    return engine_for(settings.database_url)


def save(record: FrameDetailResponse) -> None:
    frame = record.frame
    table = db.robots
    with engine().begin() as conn:
        insert = sqlite_insert if conn.dialect.name == "sqlite" else pg_insert
        upsert = insert(table).values(
            id=frame.robot_id, platform=frame.platform, latest_capture=frame.captured_at
        )
        result = conn.execute(
            upsert.on_conflict_do_update(
                index_elements=[table.c.id],
                set_={"latest_capture": frame.captured_at, "platform": frame.platform},
                where=table.c.latest_capture <= frame.captured_at,
            )
        )
        if result.rowcount == 0:
            flag("out_of_order_frame")
        conn.execute(
            db.frames.insert().values(
                **frame.model_dump(),
                job_id=record.job_id,
                status=record.status,
                expires_at=frame.received_at
                + timedelta(seconds=retention_policy(frame.platform).frame_seconds),
            )
        )


def clean_detections(detections: list[Detection]) -> list[Detection]:
    from pydantic import ValidationError

    from app.models.perception import BoundingBox

    clean = []
    seen: set[tuple] = set()
    for item in detections:
        try:
            BoundingBox.model_validate(item.bbox.model_dump())
        except ValidationError:
            flag("invalid_bbox")
            continue
        if not 0 <= item.confidence <= 1:
            flag("invalid_confidence")
            continue
        key = (item.class_label, item.bbox.x, item.bbox.y, item.bbox.w, item.bbox.h)
        if key in seen:
            flag("duplicate_detection")
            continue
        seen.add(key)
        clean.append(item)
    return clean


def finish(
    record: FrameDetailResponse,
    state: RobotState | None = None,
    error: str | None = None,
) -> None:
    frame = record.frame
    now = datetime.now(UTC)
    policy = retention_policy(frame.platform)
    with engine().begin() as conn:
        result = conn.execute(
            db.frames.update()
            .where(db.frames.c.id == frame.id)
            .values(
                status=record.status,
                expires_at=now + timedelta(seconds=policy.frame_seconds),
            )
        )
        if result.rowcount == 0:
            raise sa.exc.SQLAlchemyError("Frame expired before inference completion")
        if state is not None:
            conn.execute(
                db.robots.update()
                .where(db.robots.c.id == state.robot_id)
                .values(state_version=state.state_version)
            )
            rows = [
                dict(
                    id=d.id,
                    frame_id=frame.id,
                    robot_id=frame.robot_id,
                    captured_at=frame.captured_at,
                    class_label=d.class_label,
                    confidence=d.confidence,
                    tracker_id=d.tracker_id,
                    **d.bbox.model_dump(),
                )
                for d in record.detections
            ]
            if rows:
                conn.execute(db.detections.insert(), rows)
            conn.execute(
                db.snapshots.delete().where(
                    db.snapshots.c.robot_id == state.robot_id,
                    db.snapshots.c.platform != state.platform,
                )
            )
            conn.execute(
                db.snapshots.insert().values(
                    robot_id=state.robot_id,
                    version=state.state_version,
                    platform=state.platform,
                    created_at=state.updated_at,
                    expires_at=now + timedelta(seconds=policy.history_seconds),
                    payload=state.model_dump(mode="json"),
                )
            )
        conn.execute(
            db.events.insert().values(
                id=str(uuid4()),
                frame_id=frame.id,
                kind="frame_" + record.status,
                occurred_at=now,
                payload={"error_code": error} if error else {},
            )
        )


def get_frame(frame_id: str) -> FrameDetailResponse | None:
    from app.models.perception import Frame

    with engine().connect() as conn:
        row = (
            conn.execute(sa.select(db.frames).where(db.frames.c.id == frame_id))
            .mappings()
            .first()
        )
        if row is None:
            return None
        items = conn.execute(
            sa.select(db.detections).where(db.detections.c.frame_id == frame_id)
        ).mappings()
        return FrameDetailResponse.model_validate(
            {
                "frame": Frame.model_validate(dict(row)),
                "job_id": row.job_id,
                "status": row.status,
                "detections": [
                    dict(item, bbox={key: item[key] for key in ("x", "y", "w", "h")})
                    for item in items
                ],
            }
        )


def stored_states() -> tuple[dict[str, int], list[RobotState]]:
    with engine().connect() as conn:
        versions: dict[str, int] = dict(
            conn.execute(
                sa.select(db.robots.c.id, db.robots.c.state_version).where(
                    db.robots.c.state_version > 0
                )
            ).all()
        )
        rows: list[dict] = list(
            conn.scalars(
                sa.select(db.snapshots.c.payload)
                .where(db.snapshots.c.expires_at > datetime.now(UTC))
                .order_by(db.snapshots.c.robot_id, db.snapshots.c.version)
            ).all()
        )
    return versions, [RobotState.model_validate(row) for row in rows]


def purge(*, dry_run: bool = False, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    # Terminal records expire on policy age. Abandoned accepted frames also expire.
    expired = db.frames.c.expires_at <= now
    expired_frames = sa.select(db.frames.c.id).where(expired)
    stale = db.snapshots.c.expires_at <= now
    with engine().begin() as conn:
        counts = {
            "frames": conn.scalar(
                sa.select(sa.func.count()).select_from(db.frames).where(expired)
            )
            or 0,
            "detections": conn.scalar(
                sa.select(sa.func.count())
                .select_from(db.detections)
                .where(db.detections.c.frame_id.in_(expired_frames))
            )
            or 0,
            "state_snapshots": conn.scalar(
                sa.select(sa.func.count()).select_from(db.snapshots).where(stale)
            )
            or 0,
            "events": conn.scalar(
                sa.select(sa.func.count())
                .select_from(db.events)
                .where(db.events.c.frame_id.in_(expired_frames))
            )
            or 0,
        }
        if not dry_run:
            conn.execute(db.frames.delete().where(expired))
            conn.execute(db.snapshots.delete().where(stale))
    log.info(
        "telemetry_purge",
        extra={"purge": {"dry_run": dry_run, "at": now.isoformat(), **counts}},
    )
    return counts


def audit() -> dict[str, int]:
    """Read-only stored-data checks; intentionally not run on every request."""
    f = db.frames.c
    d = db.detections.c
    arrivals = sa.select(
        f.captured_at,
        sa.func.max(f.captured_at)
        .over(partition_by=f.robot_id, order_by=(f.received_at, f.id), rows=(None, -1))
        .label("prior_max"),
    ).subquery()
    duplicates = (
        sa.select(d.frame_id)
        .group_by(d.frame_id, d.class_label, d.x, d.y, d.w, d.h)
        .having(sa.func.count() > 1)
        .subquery()
    )
    with engine().connect() as conn:

        def count(table, *conditions):
            return (
                conn.scalar(
                    sa.select(sa.func.count()).select_from(table).where(*conditions)
                )
                or 0
            )

        age = (
            (sa.func.julianday(f.received_at) - sa.func.julianday(f.captured_at))
            * 86400
            if conn.dialect.name == "sqlite"
            else sa.extract("epoch", f.received_at - f.captured_at)
        )
        return {
            "future_capture_at_arrival": count(
                db.frames, f.captured_at > f.received_at
            ),
            "old_capture_at_arrival": count(
                db.frames, age > settings.max_capture_age_seconds
            ),
            "out_of_order_stored": count(
                arrivals, arrivals.c.captured_at < arrivals.c.prior_max
            ),
            "invalid_confidence_stored": count(
                db.detections, ~d.confidence.between(0, 1)
            ),
            "invalid_bbox_stored": count(
                db.detections,
                sa.or_(
                    ~d.x.between(0, 1),
                    ~d.y.between(0, 1),
                    d.w <= 0,
                    d.w > 1,
                    d.h <= 0,
                    d.h > 1,
                    d.x + d.w > 1.000001,
                    d.y + d.h > 1.000001,
                ),
            ),
            "duplicate_geometry_groups": count(duplicates),
        }
