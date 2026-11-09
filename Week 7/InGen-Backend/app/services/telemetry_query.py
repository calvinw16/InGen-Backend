"""Indexed keyset queries and UTC timeline aggregation."""

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Literal

import sqlalchemy as sa
from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.models import telemetry as db
from app.services.telemetry_store import engine


class DetectionQuery(BaseModel):
    robot_id: str | None = None
    class_label: str | None = None
    min_confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    sort: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def validate_range(self):
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("start must be before end")
        return self

    def scope(self) -> dict:
        return self.model_dump(mode="json", exclude={"cursor", "limit"})


def decode_cursor(query: DetectionQuery) -> tuple[datetime, str] | None:
    if query.cursor is None:
        return None
    try:
        data = json.loads(base64.b64decode(query.cursor, altchars=b"-_", validate=True))
        stamp = datetime.fromisoformat(data["at"])
        key = data["id"]
        if (
            data["scope"] != query.scope()
            or stamp.utcoffset() is None
            or not isinstance(key, str)
            or not key
        ):
            raise ValueError
        return stamp, key
    except (binascii.Error, ValueError, TypeError, KeyError) as exc:
        raise ValueError(
            "Cursor is invalid or does not match filters and sort"
        ) from exc


def detection_statement(query: DetectionQuery):
    c = db.detections.c
    stmt = sa.select(db.detections)
    if query.robot_id is not None:
        stmt = stmt.where(c.robot_id == query.robot_id)
    if query.class_label is not None:
        stmt = stmt.where(c.class_label == query.class_label)
    if query.min_confidence is not None:
        stmt = stmt.where(c.confidence >= query.min_confidence)
    if query.start is not None:
        stmt = stmt.where(c.captured_at >= query.start)
    if query.end is not None:
        stmt = stmt.where(c.captured_at < query.end)
    boundary = decode_cursor(query)
    if boundary is not None:
        key = sa.tuple_(c.captured_at, c.id)
        stmt = stmt.where(key > boundary if query.sort == "asc" else key < boundary)
    order = (
        (c.captured_at.asc(), c.id.asc())
        if query.sort == "asc"
        else (c.captured_at.desc(), c.id.desc())
    )
    return stmt.order_by(*order).limit(query.limit + 1)


def query_detections(query: DetectionQuery):
    stmt = detection_statement(query)
    with engine().connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    page = rows[: query.limit]
    cursor = None
    if len(rows) > query.limit:
        last = page[-1]
        cursor = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "at": last.captured_at.isoformat(),
                    "id": last.id,
                    "scope": query.scope(),
                },
                separators=(",", ":"),
            ).encode()
        ).decode()
    return {
        "items": [
            dict(row, bbox={key: row[key] for key in ("x", "y", "w", "h")})
            for row in page
        ],
        "count": len(page),
        "next_cursor": cursor,
    }


def timeline_statement(
    robot_id: str, start: datetime, end: datetime, bucket_seconds: int, dialect: str
):
    c = db.detections.c
    epoch = (
        sa.func.strftime("%s", c.captured_at)
        if dialect == "sqlite"
        else sa.extract("epoch", c.captured_at)
    )
    # Integer division truncates fractional seconds before UTC bucket alignment.
    epoch_seconds = sa.cast(
        sa.func.floor(epoch) if dialect != "sqlite" else epoch, sa.BigInteger
    )
    bucket = (
        epoch_seconds
        - ((epoch_seconds % bucket_seconds + bucket_seconds) % bucket_seconds)
    ).label("bucket")
    return (
        sa.select(bucket, c.class_label, sa.func.count().label("count"))
        .where(c.robot_id == robot_id, c.captured_at >= start, c.captured_at < end)
        .group_by(bucket, c.class_label)
        .order_by(bucket, c.class_label)
    )


def query_timeline(robot_id: str, start: datetime, end: datetime, bucket_seconds: int):
    buckets: dict[int, dict[str, int]] = {}
    with engine().connect() as conn:
        for epoch, label, count in conn.execute(
            timeline_statement(robot_id, start, end, bucket_seconds, conn.dialect.name)
        ):
            buckets.setdefault(epoch, {})[label] = count
    return {
        "robot_id": robot_id,
        "bucket_seconds": bucket_seconds,
        "items": [
            {
                "start": datetime.fromtimestamp(epoch, UTC),
                "count": sum(counts.values()),
                "by_class": counts,
            }
            for epoch, counts in buckets.items()
        ],
    }
