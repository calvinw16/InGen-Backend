# W06 State encoder implementation

The service now exposes current state and bounded state history for every robot.
Completed frames update the encoder before their frame record becomes completed.
The [schema](W06_State_Schema.md) defines all fields, association rules, aging,
eviction, failure cases and explicit tracker non-goals.

## Endpoints

| Method and path | Result |
| --- | --- |
| GET /v1/robots/{robot_id}/state | Current encoded RobotState; empty version 0 for unknown robots |
| GET /v1/robots/{robot_id}/state/history?limit=20 | Last N retained versions in ascending version order, with items and count |
| POST /v1/frames | Existing asynchronous JPEG submission, including required robot_id and platform |

Example: `curl 'http://localhost:8000/v1/robots/aido_001/state/history?limit=5'`.
History has a maximum count and maximum age, so requesting N need not return N.

## Concurrency design

The worker is currently a single asynchronous writer. The encoder additionally
uses one process-wide reentrant lock, serializing all robot updates and reads.
This deliberately chooses a serialized mutation design rather than per-robot
locks: association, version increment, aggregate calculation, snapshot append,
and pruning execute inside one critical section. Reads take the same lock and
return deep copies. No lock is held across an await. This prevents lost counts,
duplicate versions and partially constructed snapshots even if multiple worker
threads invoke the encoder simultaneously. Reentrancy lets history age state
through the normal get path under the same lock.

Default observation timestamps are sampled **after acquiring the lock**, so
contending threads cannot submit timestamps sampled in an earlier order and
spuriously fail backwards-time validation. Explicit replay timestamps still
reject backwards updates. This is process-local coordination; separate Uvicorn
processes have independent stores. A shared transactional database or actor
service is needed before running multiple writers across processes. The global
lock also limits parallelism across different robots; per-robot locks can be a
future throughput improvement after measurement.

## Retention hook

`app/services/retention.py` selects immutable policies by platform. The existing
frame platform now propagates into state and snapshots. Configuration:

| Setting | Default |
| --- | ---: |
| STATE_HISTORY_LIMIT | 100 snapshots per robot, configurable 1–1000 |
| STATE_HISTORY_SECONDS | 3600 seconds |
| FARI_STATE_HISTORY_SECONDS | 60 seconds |
| FRAME_RETENTION_SECONDS | 3600 seconds |
| FARI_FRAME_RETENTION_SECONDS | 60 seconds |

Durations must be finite and positive. These are implementation defaults, not
clinical retention requirements. Terminal frame metadata/detection records expire
after completion or failure plus their platform TTL. Access/save/terminal callbacks
purge expired frame records; subsequent GET returns 404. Pending jobs are not
expired while inference is in progress. Frame TTL and state-history TTL are
independent. Cleanup is lazy, with no background deletion SLA for idle processes.

Neither frame records nor state history stores image bytes. The inference-thread
wrapper explicitly closes the decoded Pillow image in finally, including model
errors. If the asynchronous wait times out, closing waits until the underlying
thread exits, so a running model does not read a prematurely closed image. Python
request bodies, inference-library caches and process memory are not securely
erased by this mechanism. Raw imagery has no archive policy for any platform.
See the Fari analysis for the resulting privacy limits.

## Verification

Run `uv run pytest`, `uv run ruff check .`, `uv run black --check .`, and
`uv run mypy app`.

`tests/test_state_history.py` checks bounded immutable snapshots, TTL boundaries,
platform policy separation, platform changes, endpoint limits and unknown robots.
A concurrency test submits four HTTP frames together and asserts all four frame
IDs appear in ordered history, versions are 1–4, and one entity has observation
count four. A separate eight-thread test performs 50 writes and checks exactly
50 unique versions, stable identity and uncorrupted observation counts.

The requested “merged” label is not asserted: this workspace has no merge action
as part of this change. Source and passing checks are available for review.
