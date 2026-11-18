import asyncio
import hmac
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.core.config import settings
from app.models import telemetry as db
from app.models.alerts import Rule
from app.models.perception import Frame, FrameDetailResponse, RobotState
from app.services.telemetry_store import finish, make_engine, save
from app.services.webhooks import deliver_one
from tests.test_robot_state import detection

TOKEN = "operator-test"
HEADERS = {"X-InGen-Operator-Token": TOKEN}
SECRET = "a" * 32
URL = "https://receiver.example/alerts"


def test_rule_window_wrap():
    rule = Rule(
        name="overnight",
        class_labels={"person"},
        utc_window={"start": "22:00", "end": "06:00"},
    )
    assert rule.utc_window.includes(datetime(2026, 1, 1, 23, tzinfo=UTC).time())
    assert not rule.utc_window.includes(datetime(2026, 1, 1, 6, tzinfo=UTC).time())


def add_frame(robot, now, match=True, platform="aido"):
    frame_id = str(uuid4())
    record = FrameDetailResponse(
        frame=Frame(
            id=frame_id,
            robot_id=robot,
            platform=platform,
            captured_at=now,
            received_at=now,
            width=100,
            height=100,
            format="jpeg",
            size_bytes=100,
            checksum="a" * 64,
        ),
        job_id=str(uuid4()),
        status="completed",
        detections=(
            [detection().model_copy(update={"id": str(uuid4()), "frame_id": frame_id})]
            if match
            else []
        ),
    )
    save(record)
    finish(
        record,
        RobotState(
            robot_id=robot,
            platform=platform,
            updated_at=now,
            state_version=version(robot) + 1,
        ),
    )
    return frame_id


def version(robot):
    from app.services import telemetry_store

    with telemetry_store.engine().connect() as conn:
        return conn.scalar(
            sa.select(db.robots.c.state_version).where(db.robots.c.id == robot)
        )


def test_alert_outbox_filters_and_acknowledgement(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", TOKEN)
    monkeypatch.setattr("app.services.webhooks.claim", lambda now: None)
    monkeypatch.setattr(settings, "webhook_allowed_urls", [URL])
    robot = "alert-" + uuid4().hex
    assert client.get("/v1/rules").status_code == 403
    assert client.get("/dashboard").status_code == 200
    assert (
        client.post(
            "/v1/webhook-subscribers",
            headers=HEADERS,
            json={"url": "http://localhost:9999/", "secret": SECRET},
        ).status_code
        == 422
    )
    subscriber = client.post(
        "/v1/webhook-subscribers", headers=HEADERS, json={"url": URL, "secret": SECRET}
    )
    assert subscriber.status_code == 201 and "secret" not in subscriber.json()
    spec = {
        "name": "Patrol intrusion",
        "robot_id": robot,
        "platform": "aido",
        "class_labels": ["person"],
        "zone": {"x": 0, "y": 0, "w": 0.5, "h": 0.5},
        "consecutive_frames": 2,
        "cooldown_seconds": 60,
    }
    rule = client.post("/v1/rules", headers=HEADERS, json=spec).json()
    now = datetime.now(UTC).replace(hour=23)
    for match in (True, False, True, True, True):
        add_frame(robot, now, match)
    params = {
        "kind": "alert",
        "robot_id": robot,
        "class_label": "person",
        "min_confidence": 0.5,
    }
    page = client.get("/v1/events", params=params).json()
    assert page["count"] == 1
    event = page["items"][0]
    assert (
        event["rule_id"] == rule["id"] and len(event["payload"]["detection_ids"]) == 1
    )
    assert (
        client.get("/v1/events", params={**params, "class_label": "vehicle"}).json()[
            "count"
        ]
        == 0
    )
    first = client.get("/v1/events", params={"robot_id": robot, "limit": 1}).json()
    second = client.get(
        "/v1/events",
        params={"robot_id": robot, "limit": 1, "cursor": first["next_cursor"]},
    ).json()
    assert first["items"][0]["id"] != second["items"][0]["id"]
    path = f"/v1/events/{event['id']}/acknowledge"
    for actor in ("Calvin", "Later"):
        response = client.post(path, headers=HEADERS, json={"actor": actor}).json()
        assert response["acknowledged_by"] == "Calvin"
    assert (
        client.get("/v1/events", params={**params, "acknowledged": False}).json()[
            "count"
        ]
        == 0
    )
    assert (
        client.put(
            f"/v1/rules/{rule['id']}",
            headers=HEADERS,
            json={**spec, "consecutive_frames": 1},
        ).status_code
        == 200
    )
    assert (
        client.post(f"/v1/rules/{rule['id']}/disable", headers=HEADERS).json()[
            "enabled"
        ]
        is False
    )
    add_frame(robot, now)
    assert client.get("/v1/events", params=params).json()["count"] == 1


def test_signed_retry_and_dead_letter(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.webhooks.engine", lambda: isolated)
    monkeypatch.setattr("app.services.telemetry_store.engine", lambda: isolated)
    isolated = make_engine(f"sqlite:///{tmp_path / 'outbox.db'}")
    config = Config("alembic.ini")
    with isolated.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
    monkeypatch.setattr(settings, "webhook_allowed_urls", [URL])
    monkeypatch.setattr(settings, "webhook_max_retries", 1)
    robot = "retry-" + uuid4().hex
    now = datetime.now(UTC)
    frame_id = add_frame(robot, now)
    job_id, subscriber_id, event_id = (str(uuid4()) for _ in range(3))
    with isolated.begin() as conn:
        conn.execute(db.outbox.delete())  # isolate this transport test
        conn.execute(
            db.subscribers.insert().values(id=subscriber_id, url=URL, secret=SECRET)
        )
        conn.execute(
            db.events.insert().values(
                id=event_id,
                frame_id=frame_id,
                kind="alert",
                occurred_at=now,
                payload={},
            )
        )
        conn.execute(
            db.outbox.insert().values(
                id=job_id,
                event_id=event_id,
                subscriber_id=subscriber_id,
                body='{"hello":"world"}',
                attempts=0,
                due=now,
            )
        )
    calls = []

    def receiver(request):
        calls.append(request)
        signature = (
            "sha256=" + hmac.digest(SECRET.encode(), request.content, "sha256").hex()
        )
        assert request.headers["X-InGen-Signature"] == signature
        assert request.headers["X-InGen-Delivery"] == job_id
        return httpx.Response(503)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as http:
            assert await deliver_one(http, now)
            assert not await deliver_one(http, now)
            assert await deliver_one(http, now + timedelta(seconds=5))

    asyncio.run(run())
    assert len(calls) == 2
    with isolated.connect() as conn:
        assert (
            conn.scalar(
                sa.select(db.dead_letters.c.attempts).where(
                    db.dead_letters.c.id == job_id
                )
            )
            == 2
        )


def test_upgrade_existing_events_and_downgrade(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'w08.db'}")
    config = Config("alembic.ini")
    with eng.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0001")
        conn.exec_driver_sql("INSERT INTO robots VALUES ('r','aido','2026-01-01',0)")
        conn.exec_driver_sql(
            "INSERT INTO frames VALUES ('f','r','aido','2026-01-01','2026-01-01',10,10,'jpeg',1,'x','j','completed','2026-01-02')"
        )
        conn.exec_driver_sql(
            "INSERT INTO events VALUES ('e','f','frame_completed','2026-01-01','{}')"
        )
        command.upgrade(config, "head")
        assert conn.scalar(sa.select(db.events.c.kind)) == "frame_completed"
        command.downgrade(config, "0001")
        assert conn.exec_driver_sql("select id from events").scalar() == "e"
    eng.dispose()
