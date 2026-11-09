# Week 07 log

This week moved the perception service from temporary frame records to a
migrated telemetry store. The initial Alembic revision defines robots, frames,
detections, state snapshots and events. A completed frame writes its detection
rows, state snapshot and lifecycle event together. The state encoder restores
completed versions when the service starts, while keeping the existing
association behavior. The Week 7 starting folder did not have an event
producer, so this work records actual frame lifecycle events without inventing
clinical event semantics.

The indexing decision that mattered most was putting equality filters before
the capture timestamp, with detection ID last as a stable tie-breaker. The
query I measured filtered on one robot, person class, confidence at least 0.7
and a two-day capture window, sorted newest first and requested 20 results.
On the local seed database of 8,167 detections, the planner used the
robot/class/capture index and did not build a temporary sort. Over 40 warmed
executions, median database execution and fetch time was 0.036 ms with the
index and 0.244 ms with the same statement forced to scan the table. The
results matched. This is a local SQL comparison, not an HTTP latency claim or
evidence of PostgreSQL performance.

Keeping confidence as a residual filter was deliberate: a confidence range
ahead of capture time would sacrifice ordered traversal. Four detection
indexes cover global, robot, class and robot-plus-class access. Those indexes
cost storage and make writes and purge deletions more expensive. The plan
capture includes 128 variants covering every filter subset in both sort
directions, with and without cursor boundaries. The timeline also uses an
indexed robot/time range, then groups rows into buckets.

Pagination seeks past the last timestamp and ID rather than counting skipped
rows. A regression test inserts a newer detection after the first page and
verifies that continuing the cursor does not repeat or skip the original
remaining records. The API still has live semantics: late arrivals and
retention can change what is available on later pages.

The Fari privacy decision was to keep zero raw image archive and use shorter
retention for derived observations. A scheduled job deletes expired rows with
cascade cleanup, and dry run reports the proposed deletions. The next
deployment check is to run the migrations and operator plans against a
representative PostgreSQL database, then measure ingestion and retention cost
under concurrent traffic.
