from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models.perception import BoundingBox, Detection, RobotState
from app.services.robot_state import RobotStateEncoder

START = datetime(2026, 1, 1, tzinfo=UTC)


def detection(x=0.1, label="person"):
    return Detection(
        id="d",
        frame_id="f",
        class_label=label,
        confidence=0.9,
        bbox=BoundingBox(x=x, y=0.1, w=0.1, h=0.1),
    )


def encoder(**kwargs):
    return RobotStateEncoder(Settings(_env_file=None, **kwargs))


def test_association_and_json_contract():
    store = encoder()
    first = store.update("r", "f1", [detection()], now=START)
    second = store.update(
        "r", "f2", [detection(0.12)], now=START + timedelta(seconds=1)
    )
    assert len(second.entities) == 1
    assert second.entities[0].entity_id == first.entities[0].entity_id
    assert second.entities[0].observation_count == 2
    assert second.entities[0].position.x == 0.12
    assert second.entities[0].last_seen == START + timedelta(seconds=1)
    assert second.state_version == 2
    assert second.most_recent_frame_id == "f2"
    assert second.entity_count_by_class == {"person": 1}
    assert RobotState.model_validate_json(second.model_dump_json()) == second
    second.entities.clear()
    assert len(store.get("r", now=START + timedelta(seconds=1)).entities) == 1


def test_class_distance_one_to_one_and_robot_isolation():
    store = encoder()
    first = store.update("r", "f1", [detection()], now=START)
    second = store.update(
        "r",
        "f2",
        [detection(), detection(0.11), detection(0.8), detection(label="vehicle")],
        now=START,
    )
    assert len(second.entities) == 4
    assert sum(e.observation_count == 2 for e in second.entities) == 1
    assert first.entities[0].entity_id in {e.entity_id for e in second.entities}
    assert store.get("other", now=START).entities == []
    assert store.get("other", now=START).state_version == 0


def test_staleness_revival_eviction_and_empty_frame():
    store = encoder(state_stale_seconds=2, state_eviction_seconds=4)
    first = store.update("r", "f1", [detection()], now=START)
    stale = store.get("r", now=START + timedelta(seconds=2))
    assert stale.entities[0].stale
    assert stale.state_version == 2
    assert store.get("r", now=START + timedelta(seconds=2)).state_version == 2
    revived = store.update("r", "f2", [detection()], now=START + timedelta(seconds=3))
    assert revived.entities[0].entity_id == first.entities[0].entity_id
    assert not revived.entities[0].stale
    empty = store.update("r", "f3", [], now=START + timedelta(seconds=5))
    assert empty.entities[0].stale
    assert empty.most_recent_frame_id == "f3"
    evicted = store.get("r", now=START + timedelta(seconds=7))
    assert evicted.entities == []
    assert evicted.entity_count_by_class == {}
    new = store.update("r", "f4", [detection()], now=START + timedelta(seconds=8))
    assert new.entities[0].entity_id != first.entities[0].entity_id


def test_hard_cap_and_invalid_times():
    store = encoder(state_max_entities=2)
    state = store.update(
        "r", "f", [detection(), detection(0.4), detection(0.8)], now=START
    )
    assert len(state.entities) == 2
    with pytest.raises(ValueError):
        store.update("r", "old", [], now=START - timedelta(seconds=1))
    with pytest.raises(ValueError):
        store.get("r", now=START.replace(tzinfo=None))


@pytest.mark.parametrize(
    "values",
    [
        {"state_stale_seconds": 5, "state_eviction_seconds": 5},
        {"state_association_threshold": -1},
        {"state_max_entities": 0},
        {"state_stale_seconds": float("nan")},
    ],
)
def test_invalid_config(values):
    with pytest.raises(ValidationError):
        encoder(**values)


def test_threshold_boundary():
    store = encoder(state_association_threshold=0)
    first = store.update("r", "f1", [detection()], now=START)
    second = store.update("r", "f2", [detection()], now=START)
    assert len(second.entities) == 1
    assert second.entities[0].entity_id == first.entities[0].entity_id


def test_completed_frames_feed_state_endpoint(client):
    import time

    from tests.test_v1 import create_test_image

    for index in range(2):
        response = client.post(
            "/v1/frames",
            json={
                "robot_id": "encoder-integration",
                "platform": "test",
                "timestamp": datetime.now(UTC).isoformat(),
                "image_base64": create_test_image(),
            },
        )
        assert response.status_code == 202
        frame_id = response.json()["frame_id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if client.get(f"/v1/frames/{frame_id}").json()["status"] == "completed":
                break
            time.sleep(0.001)
        state = client.get("/v1/robots/encoder-integration/state").json()
        assert state["most_recent_frame_id"] == frame_id
        assert state["state_version"] == index + 1
        assert state["entity_count_by_class"] == {"person": 1}
        assert state["entities"][0]["observation_count"] == index + 1
