# W06 RobotState schema

Completed inference frames now update per-robot state before their frame record
is marked completed. `GET /v1/robots/{robot_id}/state` returns the encoded state.
This replaces the previous placeholder `state` and `source` response fields;
consumers of that placeholder must migrate to the contract below.

## JSON contract

```json
{
  "robot_id": "aido_001",
  "platform": "aido",
  "entities": [
    {
      "entity_id": "d0950a3c-15b8-4331-a106-839be966f51e",
      "class_label": "person",
      "last_seen": "2026-11-02T15:00:00Z",
      "position": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.3},
      "confidence": 0.9,
      "observation_count": 2,
      "stale": false
    }
  ],
  "entity_count_by_class": {"person": 1},
  "most_recent_frame_id": "frame_002",
  "state_version": 2,
  "updated_at": "2026-11-02T15:00:00Z"
}
```

`position` is the last observed normalized bounding box: top-left x/y and
width/height, relative to the original image, with positive extents and bounds
inside [0, 1]. It is image space, not world coordinates. Confidence is the last
observation's score, not an average. Entity IDs are UUIDs independent of detection
IDs and tracker IDs. Counts include stale entities until eviction, and absent
classes are omitted. Sum the class counts for the retained entity total.

Unknown robots return an empty entity list and count dictionary, null frame ID
and updated time, and version 0. No placeholder entity is generated.
Pydantic models define the contract in `app/models/perception.py`; JSON is
available through the endpoint or `state.model_dump_json()`.

## Association rule

`app/services/robot_state.py` holds the thread-safe encoder. For each completed
frame, first age existing entities. Form candidate pairs having exactly the same
class label and Euclidean center-to-center distance at or below the configured
threshold. Sort by distance, then entity ID and detection input index for ties;
greedily accept pairs while using each entity and detection at most once. This
is a simple global greedy association, not an optimal assignment algorithm.

Matched entities retain their ID, replace position/confidence, update last_seen,
increment observation_count, and clear stale. Each unmatched detection creates
an entity with count 1. Unmatched entities retain their prior observation.
Stale entities remain eligible for association until evicted. Empty frames still
age entities, update most_recent_frame_id, and increment the version.

Observation time is backend completion time in UTC, not camera capture time.
Thus delayed frames are associated in completion order. The service's single
worker serializes completion. Direct encoder callers can supply a timezone-aware
`now` for deterministic replay; backwards update times are rejected. State reads
clamp time to updated_at if the system clock moves backwards.

## Staleness and bounds

Environment settings, validated at startup:

| Variable | Default | Meaning |
| --- | ---: | --- |
| STATE_ASSOCIATION_THRESHOLD | 0.15 | Maximum normalized center distance, inclusive; range 0 to sqrt(2) |
| STATE_STALE_SECONDS | 5 | Mark stale when age is at least this many seconds |
| STATE_EVICTION_SECONDS | 30 | Remove when age is at least this many seconds |
| STATE_MAX_ENTITIES | 256 | Hard cap per robot, positive integer |

Both windows must be finite and positive, and eviction must exceed staleness.
Age is measured since last_seen, not since the stale transition. Aging happens
on frame updates and GET reads, so a robot with no new frames still returns
aged state. No background cleanup task runs: unqueried state is physically
cleaned at its next access. At the hard cap, oldest last_seen entries are removed
first, breaking ties by UUID. This bounds retained entities per robot even when
many unmatched objects arrive inside the eviction window. Robot records
and version metadata remain in memory; the number of distinct robots is not
capped. This is not a persistent store and resets on restart. Multiple service
processes have independent state.

Every frame update increments state_version once, including empty detections.
A GET that changes staleness or removes entities increments it once; unchanged
GETs leave it alone. updated_at records that mutation time. Expiration on GET
keeps most_recent_frame_id unchanged. Snapshots are deep copies so consumers
cannot mutate stored entities. Failed inference does not update state.

## Known limitations and non-goals

This is **not a Kalman filter or a full multi-object tracker**. It has no motion
prediction, appearance embedding, camera-motion compensation or world-space
localization. Occlusion can mark an entity stale and ultimately remove it;
reappearance after eviction gets a new ID. Fast motion beyond the distance
threshold fragments identity. Two adjacent objects of the same class, especially
when crossing, can swap IDs; greedy association and deterministic tie breaking
do not resolve that ambiguity. Class-label changes create a separate entity.
Camera movement and different camera views under one robot ID can also break
association. Count and position fields describe observations, not safety or
navigation guarantees.

## Validation

Run `uv run pytest tests/test_robot_state.py tests/test_v1.py`. Tests cover stable
identity, observation counts and coordinates, class/distance separation,
one-to-one matching, robot isolation, threshold equality, stale/revival/eviction
boundaries, empty updates, hard cap, invalid settings/times, snapshot isolation,
JSON round-trip and completed-frame-to-endpoint integration.


## W06 history and platform extension

`platform` is copied from the frame's existing required platform discriminator.
Unknown robots use `"unknown"`. Platform strings remain open for compatibility;
retention recognizes `fari` case-insensitively, with the default policy otherwise.
Changing a robot's platform clears its entities and prior history to prevent
association across platforms, while preserving the increasing state_version.
Clients should use stable robot IDs and stable platform strings.

`GET /v1/robots/{robot_id}/state/history?limit=20` returns:

```json
{"robot_id":"aido_001","items":[],"count":0}
```

`items` contains the last N retained **complete RobotState snapshots**, oldest to
newest, including the latest version when retained. `count` is the returned item
count. Limit accepts 1–1000 (invalid values return 422); the configured capacity
may be lower. Unknown robots return 200 and empty history. Version 0 is not
recorded. Every committed version, including aging changes on reads, is copied
into history atomically. Snapshots never change when current entities change.
History reads first age current state and can therefore append an aging version.
Retention can remove earlier snapshots, so history is not an immutable audit log
and version gaps are expected. Both endpoints return independent deep copies.

History is bounded by STATE_HISTORY_LIMIT (default 100) and age: default
STATE_HISTORY_SECONDS=3600, FARI_STATE_HISTORY_SECONDS=60. Expire at age >= TTL.
History pruning occurs on state update, state read and history read. Empty
history can coexist with a retained current state; current entities continue to
use the separate staleness/eviction windows above. The cap bounds snapshots per
robot, not the number of robot IDs. All storage is process-local and volatile.

See [implementation and concurrency](W06_State_Encoder.md) and
[Fari gap analysis](W06_Fari_Gap_Analysis.md) for policy scope and tests.
