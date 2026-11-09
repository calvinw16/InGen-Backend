import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.services import frame_store
from app.services.retention import retention_policy
from tests.test_robot_state import START, detection, encoder
from tests.test_v1 import create_test_image


def test_history_bounded_immutable_and_platform_retention():
    store = encoder(state_history_limit=2, fari_state_history_seconds=2)
    for index in range(3):
        store.update("r", str(index), [detection()], now=START, platform="fari")
    snapshots = store.history("r", now=START)
    assert [s.state_version for s in snapshots] == [2, 3]
    assert [s.entities[0].observation_count for s in snapshots] == [2, 3]
    snapshots[0].entities.clear()
    assert len(store.history("r", now=START)[0].entities) == 1
    assert store.history("r", now=START + timedelta(seconds=2)) == []
    store.update("r", "new", [], now=START + timedelta(seconds=3), platform="aido")
    assert [
        s.state_version for s in store.history("r", now=START + timedelta(seconds=3))
    ] == [4]
    assert store.history("absent", now=START) == []


def test_concurrent_encoder_writes():
    store = encoder(state_history_limit=100)

    def update(index):
        return store.update("r", str(index), [detection()])

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(update, range(50)))
    assert sorted(s.state_version for s in results) == list(range(1, 51))
    state = store.get("r")
    assert len(state.entities) == 1
    assert state.entities[0].observation_count == 50
    assert [s.state_version for s in store.history("r", 100)] == list(range(1, 51))


def test_concurrent_frame_submission_and_history(client):
    payload = {
        "robot_id": "concurrent-w06",
        "platform": "fari",
        "timestamp": datetime.now(UTC).isoformat(),
        "image_base64": create_test_image(),
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(
            pool.map(lambda _: client.post("/v1/frames", json=payload), range(4))
        )
    assert all(r.status_code == 202 for r in responses)
    frame_ids = {r.json()["frame_id"] for r in responses}
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if all(
            client.get(f"/v1/frames/{fid}").json()["status"] == "completed"
            for fid in frame_ids
        ):
            break
        time.sleep(0.001)
    state = client.get("/v1/robots/concurrent-w06/state").json()
    assert state["state_version"] == 4
    assert state["platform"] == "fari"
    assert state["entity_count_by_class"] == {"person": 1}
    assert state["entities"][0]["observation_count"] == 4
    history = client.get("/v1/robots/concurrent-w06/state/history?limit=4").json()
    assert history["count"] == 4
    assert [s["state_version"] for s in history["items"]] == [1, 2, 3, 4]
    assert {s["most_recent_frame_id"] for s in history["items"]} == frame_ids
    assert (
        client.get("/v1/robots/concurrent-w06/state/history?limit=0").status_code == 422
    )
    assert (
        client.get("/v1/robots/concurrent-w06/state/history?limit=1001").status_code
        == 422
    )
    assert client.get("/v1/robots/w06-absent/state/history").json()["items"] == []
    record = frame_store.frames[next(iter(frame_ids))]
    assert record._expires_at is not None
    assert 0 < (record._expires_at - datetime.now(UTC)).total_seconds() <= 60
    record._expires_at = datetime.now(UTC) - timedelta(seconds=1)
    from app.models import telemetry as db
    from app.services.telemetry_store import engine, purge

    with engine().begin() as conn:
        conn.execute(
            db.frames.update()
            .where(db.frames.c.id == record.frame.id)
            .values(expires_at=record._expires_at)
        )
    purge()
    assert client.get(f"/v1/frames/{record.frame.id}").status_code == 404


def test_retention_policy_separation():
    config = Settings(_env_file=None)
    fari = retention_policy("Fari", config)
    aido = retention_policy("aido", config)
    assert fari.frame_seconds < aido.frame_seconds
    assert fari.history_seconds < aido.history_seconds
    assert fari.raw_image_seconds == aido.raw_image_seconds == 0
