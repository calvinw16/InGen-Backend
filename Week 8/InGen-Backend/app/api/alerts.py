"""Operator rule management, event queries, acknowledgement and subscribers."""

import base64
import hmac
import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.core.config import settings
from app.models import telemetry as db
from app.models.alerts import Acknowledgement, Label, Rule, Severity, Subscriber
from app.services.telemetry_query import DetectionQuery, decode_cursor
from app.services.telemetry_store import engine

router = APIRouter(prefix="/v1", tags=["Alerts"])


def operator(
    token: Annotated[str, Header(alias="X-InGen-Operator-Token")] = "",
) -> None:
    if not settings.operator_token or not hmac.compare_digest(
        token.encode(), settings.operator_token.encode()
    ):
        raise HTTPException(
            403,
            detail={
                "code": "OPERATOR_REQUIRED",
                "message": "An operator token is required.",
            },
        )


def missing(code: str):
    return HTTPException(404, detail={"code": code, "message": "Resource not found."})


@router.get("/rules", dependencies=[Depends(operator)])
def list_rules():
    with engine().connect() as conn:
        return [
            {"id": row.id, **row.spec}
            for row in conn.execute(sa.select(db.rules).order_by(db.rules.c.id))
        ]


@router.post("/rules", status_code=201, dependencies=[Depends(operator)])
def create_rule(rule: Rule):
    rule_id = str(uuid4())
    spec = rule.model_dump(mode="json")
    with engine().begin() as conn:
        conn.execute(db.rules.insert().values(id=rule_id, spec=spec))
    return {"id": rule_id, **spec}


@router.put("/rules/{rule_id}", dependencies=[Depends(operator)])
def update_rule(rule_id: str, rule: Rule):
    spec = rule.model_dump(mode="json")
    with engine().begin() as conn:
        result = conn.execute(
            db.rules.update().where(db.rules.c.id == rule_id).values(spec=spec)
        )
        if not result.rowcount:
            raise missing("RULE_NOT_FOUND")
        conn.execute(db.progress.delete().where(db.progress.c.rule_id == rule_id))
    return {"id": rule_id, **spec}


@router.post("/rules/{rule_id}/disable", dependencies=[Depends(operator)])
def disable_rule(rule_id: str):
    with engine().begin() as conn:
        spec = conn.scalar(
            sa.select(db.rules.c.spec).where(db.rules.c.id == rule_id).with_for_update()
        )
        if spec is None:
            raise missing("RULE_NOT_FOUND")
        spec = {**spec, "enabled": False}
        conn.execute(
            db.rules.update().where(db.rules.c.id == rule_id).values(spec=spec)
        )
        conn.execute(db.progress.delete().where(db.progress.c.rule_id == rule_id))
    return {"id": rule_id, **spec}


class EventQuery(DetectionQuery):
    robot_id: Label | None = None
    class_label: Label | None = None
    severity: Severity | None = None
    rule_id: Label | None = None
    kind: Label | None = None
    acknowledged: bool | None = None


@router.get("/events")
def list_events(query: Annotated[EventQuery, Query()]):
    c, f, d = db.events.c, db.frames.c, db.detections.c
    stmt = sa.select(db.events, f.robot_id, f.platform, f.captured_at).join(
        db.frames, c.frame_id == f.id
    )
    for column, value in (
        (f.robot_id, query.robot_id),
        (c.severity, query.severity),
        (c.rule_id, query.rule_id),
        (c.kind, query.kind),
    ):
        if value is not None:
            stmt = stmt.where(column == value)
    if query.start is not None:
        stmt = stmt.where(c.occurred_at >= query.start)
    if query.end is not None:
        stmt = stmt.where(c.occurred_at < query.end)
    if query.acknowledged is not None:
        stmt = stmt.where(
            c.acknowledged_at.is_not(None)
            if query.acknowledged
            else c.acknowledged_at.is_(None)
        )
    if query.class_label is not None or query.min_confidence is not None:
        linked = sa.select(d.id).where(d.frame_id == c.frame_id)
        if query.class_label is not None:
            linked = linked.where(d.class_label == query.class_label)
        if query.min_confidence is not None:
            linked = linked.where(d.confidence >= query.min_confidence)
        # Alert filters match triggering detections, not unrelated frame objects.
        with engine().connect() as conn:
            if conn.dialect.name == "sqlite":
                ids = sa.func.json_each(c.payload, "$.detection_ids").table_valued(
                    "value"
                )
            else:
                ids = (
                    sa.func.json_array_elements_text(c.payload["detection_ids"])
                    .table_valued("value")
                    .render_derived()
                )
            stmt = stmt.where(
                linked.where(
                    sa.or_(
                        c.kind != "alert",
                        d.id.in_(sa.select(ids.c.value).correlate(db.events)),
                    )
                ).exists()
            )
    try:
        boundary = decode_cursor(query)
    except ValueError as exc:
        raise HTTPException(
            422, detail={"code": "INVALID_CURSOR", "message": str(exc)}
        ) from exc
    key = sa.tuple_(c.occurred_at, c.id)
    if boundary is not None:
        stmt = stmt.where(key > boundary if query.sort == "asc" else key < boundary)
    order = (
        (c.occurred_at.asc(), c.id.asc())
        if query.sort == "asc"
        else (c.occurred_at.desc(), c.id.desc())
    )
    with engine().connect() as conn:
        rows = (
            conn.execute(stmt.order_by(*order).limit(query.limit + 1)).mappings().all()
        )
    page = rows[: query.limit]
    cursor = None
    if len(rows) > query.limit:
        last = page[-1]
        cursor = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "at": last.occurred_at.isoformat(),
                    "id": last.id,
                    "scope": query.scope(),
                }
            ).encode()
        ).decode()
    return {
        "items": [dict(row) for row in page],
        "count": len(page),
        "next_cursor": cursor,
    }


@router.post("/events/{event_id}/acknowledge", dependencies=[Depends(operator)])
def acknowledge(event_id: str, body: Acknowledgement):
    c = db.events.c
    with engine().begin() as conn:
        conn.execute(
            db.events.update()
            .where(c.id == event_id, c.acknowledged_at.is_(None))
            .values(acknowledged_by=body.actor, acknowledged_at=datetime.now(UTC))
        )
        row = (
            conn.execute(sa.select(db.events).where(c.id == event_id))
            .mappings()
            .first()
        )
        if row is None:
            raise missing("EVENT_NOT_FOUND")
        return dict(row)


@router.get("/webhook-subscribers", dependencies=[Depends(operator)])
def list_subscribers():
    with engine().connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sa.select(db.subscribers.c.id, db.subscribers.c.url)
            ).mappings()
        ]


@router.post("/webhook-subscribers", status_code=201, dependencies=[Depends(operator)])
def register(subscriber: Subscriber):
    url = str(subscriber.url)
    if (
        subscriber.url.username
        or subscriber.url.password
        or subscriber.url.fragment
        or url not in settings.webhook_allowed_urls
    ):
        raise HTTPException(
            422,
            detail={
                "code": "WEBHOOK_DESTINATION_DENIED",
                "message": "Use a configured receiver URL.",
            },
        )
    key = str(uuid4())
    with engine().begin() as conn:
        conn.execute(
            db.subscribers.insert().values(
                id=key, url=url, secret=subscriber.secret.get_secret_value()
            )
        )
    return {"id": key, "url": url}


@router.get("/admin/dead-letters", dependencies=[Depends(operator)])
def inspect_dead_letters(limit: Annotated[int, Query(ge=1, le=100)] = 20):
    with engine().connect() as conn:
        return {
            "items": [
                dict(row)
                for row in conn.execute(
                    sa.select(db.dead_letters)
                    .order_by(
                        db.dead_letters.c.failed_at.desc(), db.dead_letters.c.id.desc()
                    )
                    .limit(limit)
                ).mappings()
            ]
        }


@router.get("/robots")
def list_robots(limit: Annotated[int, Query(ge=1, le=100)] = 100, after: str = ""):
    with engine().connect() as conn:
        c = db.robots.c
        rows = (
            conn.execute(
                sa.select(c.id, c.platform)
                .where(c.id > after)
                .order_by(c.id)
                .limit(limit + 1)
            )
            .mappings()
            .all()
        )
    return {
        "items": [dict(row) for row in rows[:limit]],
        "next_after": rows[limit - 1].id if len(rows) > limit else None,
    }
