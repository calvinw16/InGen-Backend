import itertools
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from app.models import telemetry as db
from app.services.telemetry_query import DetectionQuery, detection_statement
from app.services.telemetry_store import (
    audit,
    clean_detections,
    engine,
    make_engine,
    purge,
    quality_stats,
)
from scripts.explain_telemetry import explain
from scripts.seed_telemetry import seed
from tests.test_robot_state import detection
from tests.test_v1 import create_test_image

ANCHOR = datetime(2026, 1, 10, tzinfo=UTC)


@pytest.fixture(scope="module")
def dataset(client):
    result = seed(3, 3, 40, ANCHOR)
    robot_id = result["prefix"] + "-00"
    with engine().connect() as conn:
        rows = conn.execute(sa.select(db.detections)).mappings().all()
    return robot_id, rows


@pytest.mark.parametrize("sort", ["asc", "desc"])
@pytest.mark.parametrize("mask", list(itertools.product((False, True), repeat=5)))
def test_all_filter_combinations(client, dataset, mask, sort):
    robot_id, _ = dataset
    start = ANCHOR - timedelta(days=2)
    end = ANCHOR - timedelta(days=1)
    values = {
        "robot_id": robot_id,
        "class_label": "person",
        "min_confidence": 0.7,
        "start": start,
        "end": end,
    }
    filters = {
        key: value
        for (key, value), use in zip(values.items(), mask, strict=True)
        if use
    }
    # Query fresh data: other modules also exercise the live worker.
    with engine().connect() as conn:
        rows = conn.execute(sa.select(db.detections)).mappings().all()
        plan = explain(conn, detection_statement(DetectionQuery(**filters, sort=sort)))
    assert any("USING INDEX ix_detection_" in line for line in plan), plan
    assert not any("TEMP B-TREE FOR ORDER BY" in line for line in plan), plan
    checks = (
        lambda r: r.robot_id == robot_id,
        lambda r: r.class_label == "person",
        lambda r: r.confidence >= 0.7,
        lambda r: r.captured_at >= start,
        lambda r: r.captured_at < end,
    )
    expected = sorted(
        (
            r
            for r in rows
            if all(not use or check(r) for use, check in zip(mask, checks, strict=True))
        ),
        key=lambda r: (r.captured_at, r.id),
        reverse=sort == "desc",
    )
    params = {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in filters.items()
    }
    response = client.get("/v1/detections", params={**params, "sort": sort, "limit": 7})
    assert response.status_code == 200
    assert [r["id"] for r in response.json()["items"]] == [r.id for r in expected[:7]]
    assert bool(response.json()["next_cursor"]) == (len(expected) > 7)


def test_keyset_survives_newer_insert_and_ties(client, dataset):
    robot_id, _ = dataset
    params = {"robot_id": robot_id, "sort": "desc", "limit": 3}
    first = client.get("/v1/detections", params=params).json()
    with engine().begin() as conn:
        old = (
            conn.execute(
                sa.select(db.detections)
                .where(db.detections.c.robot_id == robot_id)
                .order_by(db.detections.c.captured_at.desc(), db.detections.c.id.desc())
            )
            .mappings()
            .all()
        )
        new = dict(old[0], id=str(uuid4()), class_label="newer", captured_at=ANCHOR)
        conn.execute(db.detections.insert().values(**new))
    seen = [item["id"] for item in first["items"]]
    cursor = first["next_cursor"]
    while cursor:
        response = client.get("/v1/detections", params={**params, "cursor": cursor})
        assert response.status_code == 200
        body = response.json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
    assert seen == [r.id for r in old]
    for cursor, sort in (("!!bad", "desc"), (first["next_cursor"], "asc")):
        assert (
            client.get(
                "/v1/detections", params={**params, "cursor": cursor, "sort": sort}
            ).json()["code"]
            == "INVALID_CURSOR"
        )


def test_timeline(client, dataset):
    robot_id, _ = dataset
    start = ANCHOR - timedelta(days=1)
    response = client.get(
        f"/v1/robots/{robot_id}/timeline",
        params={
            "start": start.isoformat(),
            "end": ANCHOR.isoformat(),
            "bucket_seconds": 3600,
        },
    )
    assert response.status_code == 200
    buckets = response.json()["items"]
    assert buckets
    with engine().connect() as conn:
        count = conn.scalar(
            sa.select(sa.func.count())
            .select_from(db.detections)
            .where(
                db.detections.c.robot_id == robot_id,
                db.detections.c.captured_at >= start,
                db.detections.c.captured_at < ANCHOR,
            )
        )
    assert sum(b["count"] for b in buckets) == count
    assert all(b["count"] == sum(b["by_class"].values()) for b in buckets)
    assert (
        client.get(
            f"/v1/robots/{robot_id}/timeline",
            params={"start": ANCHOR.isoformat(), "end": start.isoformat()},
        ).status_code
        == 422
    )


def test_purge_dry_run_and_cascades(client):
    now = datetime.now(UTC)
    result = seed(1, 3, 2, now)
    robot = result["prefix"] + "-02"
    survivor = result["prefix"] + "-00"
    with engine().begin() as conn:
        # Fari and Aido have different default expiry deadlines.
        fari = conn.scalar(
            sa.select(sa.func.min(db.frames.c.expires_at)).where(
                db.frames.c.robot_id == robot
            )
        )
        aido = conn.scalar(
            sa.select(sa.func.min(db.frames.c.expires_at)).where(
                db.frames.c.robot_id == survivor
            )
        )
        assert now < fari < aido
        for table in (db.frames, db.snapshots):
            conn.execute(
                table.update()
                .where(table.c.robot_id == robot)
                .values(expires_at=now - timedelta(seconds=1))
            )
        ids = conn.scalars(
            sa.select(db.frames.c.id).where(db.frames.c.robot_id == robot)
        ).all()
    preview = purge(dry_run=True, now=now)
    assert (
        preview["frames"] >= 2
        and preview["state_snapshots"] >= 2
        and preview["events"] >= 2
    )
    assert purge(now=now) == preview
    with engine().connect() as conn:
        for table, column in (
            (db.frames, db.frames.c.id),
            (db.detections, db.detections.c.frame_id),
            (db.events, db.events.c.frame_id),
        ):
            assert (
                conn.scalar(
                    sa.select(sa.func.count()).select_from(table).where(column.in_(ids))
                )
                == 0
            )
        assert (
            conn.scalar(
                sa.select(sa.func.count())
                .select_from(db.snapshots)
                .where(db.snapshots.c.robot_id == robot)
            )
            == 0
        )
        assert (
            conn.scalar(
                sa.select(sa.func.count())
                .select_from(db.frames)
                .where(db.frames.c.robot_id == survivor)
            )
            == 2
        )


def test_quality_ingestion_and_durable_completion(client):
    now = datetime.now(UTC)
    robot = "quality-" + uuid4().hex
    payload = {
        "robot_id": robot,
        "platform": "aido",
        "image_base64": create_test_image(),
    }
    before = quality_stats()

    def submit(at):
        return client.post("/v1/frames", json={**payload, "timestamp": at.isoformat()})

    assert submit(now + timedelta(minutes=1)).json()["code"] == "FUTURE_TIMESTAMP"
    assert submit(now - timedelta(days=2)).json()["code"] == "OLD_TIMESTAMP"
    for stamp in (now, now - timedelta(seconds=5)):
        result = submit(stamp)
        assert result.status_code == 202
        frame_id = result.json()["frame_id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if client.get(f"/v1/frames/{frame_id}").json()["status"] == "completed":
                break
            time.sleep(0.002)
        with engine().connect() as conn:
            assert (
                conn.scalar(
                    sa.select(db.frames.c.status).where(db.frames.c.id == frame_id)
                )
                == "completed"
            )
            assert (
                conn.scalar(
                    sa.select(db.events.c.kind).where(db.events.c.frame_id == frame_id)
                )
                == "frame_completed"
            )
    sample = detection()
    assert clean_detections(
        [
            sample,
            sample,
            sample.model_copy(update={"confidence": float("nan")}),
            sample.model_copy(
                update={"bbox": sample.bbox.model_copy(update={"x": 1.5})}
            ),
        ]
    ) == [sample]
    after = client.get("/v1/admin/stats").json()["data_quality"]
    assert all(after[key] == before[key] + 1 for key in before)
    assert audit()["out_of_order_stored"] >= 1
    assert audit()["invalid_bbox_stored"] == 0


def test_database_checks_and_migration_round_trip(tmp_path):
    database = make_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    config = Config("alembic.ini")
    with database.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        assert set(sa.inspect(conn).get_table_names()) >= {
            "robots",
            "frames",
            "detections",
            "events",
            "state_snapshots",
        }
        with pytest.raises(IntegrityError):
            conn.execute(
                db.detections.insert().values(
                    id="invalid",
                    robot_id="missing",
                    frame_id="missing",
                    captured_at=ANCHOR,
                    class_label="person",
                    confidence=2,
                    x=0,
                    y=0,
                    w=0.1,
                    h=0.1,
                )
            )
        command.downgrade(config, "base")
        assert "detections" not in sa.inspect(conn).get_table_names()
    database.dispose()
