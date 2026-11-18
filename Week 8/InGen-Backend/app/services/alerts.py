"""Evaluate rule data within the frame completion transaction."""

import json
from datetime import datetime, timedelta
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.models import telemetry as db
from app.models.alerts import Rule
from app.models.perception import FrameDetailResponse, RobotState


def evaluate(
    conn: Connection, record: FrameDetailResponse, state: RobotState, now: datetime
) -> None:
    frame = record.frame
    r = db.rules.c
    # Edits and evaluation serialize on each rule row in PostgreSQL.
    for rule_id, spec in conn.execute(
        sa.select(r.id, r.spec).order_by(r.id).with_for_update()
    ):
        rule = Rule.model_validate(spec)
        if not rule.enabled or (rule.robot_id and rule.robot_id != frame.robot_id):
            continue
        p = db.progress.c
        key = (p.rule_id == rule_id, p.robot_id == frame.robot_id)
        previous = conn.execute(sa.select(db.progress).where(*key)).mappings().first()
        last_fired = previous.last_fired if previous else None
        scope_matches = (
            not rule.platform or rule.platform.casefold() == frame.platform.casefold()
        )
        window_matches = not rule.utc_window or rule.utc_window.includes(
            frame.captured_at.time()
        )
        matches = []
        if scope_matches and window_matches:
            for item in record.detections:
                if (
                    item.class_label not in rule.class_labels
                    or item.confidence < rule.min_confidence
                ):
                    continue
                if rule.zone:
                    x, y = item.bbox.x + item.bbox.w / 2, item.bbox.y + item.bbox.h / 2
                    zone = rule.zone
                    if not (
                        zone.x <= x <= zone.x + zone.w
                        and zone.y <= y <= zone.y + zone.h
                    ):
                        continue
                matches.append(item.id)
        streak = 0
        if matches:
            same_platform = (
                previous is not None
                and previous.platform.casefold() == frame.platform.casefold()
            )
            streak = min(
                rule.consecutive_frames,
                1 + (previous.streak if same_platform and previous is not None else 0),
            )
        ready = streak >= rule.consecutive_frames and (
            last_fired is None
            or now - last_fired >= timedelta(seconds=rule.cooldown_seconds)
        )
        if ready:
            last_fired = now
            event_id = str(uuid4())
            payload = {
                "rule_name": rule.name,
                "detection_ids": matches,
                "state_version": state.state_version,
            }
            conn.execute(
                db.events.insert().values(
                    id=event_id,
                    frame_id=frame.id,
                    kind="alert",
                    rule_id=rule_id,
                    severity=rule.severity,
                    occurred_at=now,
                    payload=payload,
                )
            )
            body = json.dumps(
                {
                    **payload,
                    "id": event_id,
                    "kind": "alert",
                    "rule_id": rule_id,
                    "severity": rule.severity,
                    "occurred_at": now.isoformat(),
                    "frame_id": frame.id,
                    "robot_id": frame.robot_id,
                    "platform": frame.platform,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            for (subscriber_id,) in conn.execute(sa.select(db.subscribers.c.id)):
                conn.execute(
                    db.outbox.insert().values(
                        id=str(uuid4()),
                        event_id=event_id,
                        subscriber_id=subscriber_id,
                        body=body,
                        attempts=0,
                        due=now,
                    )
                )
        values = {
            "streak": streak,
            "last_fired": last_fired,
            "platform": frame.platform,
        }
        if previous:
            conn.execute(db.progress.update().where(*key).values(**values))
        elif matches:
            conn.execute(
                db.progress.insert().values(
                    rule_id=rule_id, robot_id=frame.robot_id, **values
                )
            )
