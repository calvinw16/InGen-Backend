"""Portable SQLAlchemy 2 schema for perception telemetry."""

from datetime import UTC

import sqlalchemy as sa

metadata = sa.MetaData()


class UTCDateTime(sa.TypeDecorator):
    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.utcoffset() is None:
            raise ValueError("Telemetry timestamps require a timezone")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC)
            if value.utcoffset() is None
            else value.astimezone(UTC)
        )


robots = sa.Table(
    "robots",
    metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("platform", sa.String, nullable=False),
    sa.Column("latest_capture", UTCDateTime(), nullable=False),
    sa.Column("state_version", sa.Integer, server_default="0", nullable=False),
)

frames = sa.Table(
    "frames",
    metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("robot_id", sa.ForeignKey("robots.id"), nullable=False),
    sa.Column("platform", sa.String, nullable=False),
    sa.Column("captured_at", UTCDateTime(), nullable=False),
    sa.Column("received_at", UTCDateTime(), nullable=False),
    sa.Column("width", sa.Integer, nullable=False),
    sa.Column("height", sa.Integer, nullable=False),
    sa.Column("format", sa.String, nullable=False),
    sa.Column("size_bytes", sa.Integer, nullable=False),
    sa.Column("checksum", sa.String(64), nullable=False),
    sa.Column("job_id", sa.String, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("expires_at", UTCDateTime(), nullable=False),
    sa.CheckConstraint("captured_at <= received_at", name="ck_frame_timestamp_order"),
    sa.Index("ix_frames_robot_capture", "robot_id", "captured_at"),
    sa.Index("ix_frames_expiry", "expires_at"),
)

detections = sa.Table(
    "detections",
    metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column(
        "frame_id", sa.ForeignKey("frames.id", ondelete="CASCADE"), nullable=False
    ),
    sa.Column("robot_id", sa.ForeignKey("robots.id"), nullable=False),
    sa.Column("captured_at", UTCDateTime(), nullable=False),
    sa.Column("class_label", sa.String, nullable=False),
    sa.Column("confidence", sa.Float, nullable=False),
    *(sa.Column(name, sa.Float, nullable=False) for name in ("x", "y", "w", "h")),
    sa.Column("tracker_id", sa.Integer),
    sa.CheckConstraint(
        "confidence >= 0 AND confidence <= 1", name="ck_detection_confidence"
    ),
    sa.CheckConstraint(
        "x >= 0 AND y >= 0 AND w > 0 AND h > 0 AND x + w <= 1.000001 AND y + h <= 1.000001 AND x <= 1 AND y <= 1 AND w <= 1 AND h <= 1",
        name="ck_detection_bbox",
    ),
    sa.UniqueConstraint(
        "frame_id",
        "class_label",
        "x",
        "y",
        "w",
        "h",
        name="uq_frame_detection_geometry",
    ),
    sa.Index("ix_detection_capture", "captured_at", "id"),
    sa.Index("ix_detection_robot_capture", "robot_id", "captured_at", "id"),
    sa.Index("ix_detection_class_capture", "class_label", "captured_at", "id"),
    sa.Index(
        "ix_detection_robot_class_capture",
        "robot_id",
        "class_label",
        "captured_at",
        "id",
    ),
)

snapshots = sa.Table(
    "state_snapshots",
    metadata,
    sa.Column("robot_id", sa.ForeignKey("robots.id"), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("platform", sa.String, nullable=False),
    sa.Column("created_at", UTCDateTime(), nullable=False),
    sa.Column("expires_at", UTCDateTime(), nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Index("ix_snapshot_expiry", "expires_at"),
)

events = sa.Table(
    "events",
    metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column(
        "frame_id", sa.ForeignKey("frames.id", ondelete="CASCADE"), nullable=False
    ),
    sa.Column("kind", sa.String, nullable=False),
    sa.Column("occurred_at", UTCDateTime(), nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Index("ix_event_frame", "frame_id"),
)
