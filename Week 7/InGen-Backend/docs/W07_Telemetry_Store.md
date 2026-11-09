# W07 telemetry store

Run from the Week 7 backend root:

```sh
uv sync --locked
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8000
```

The default database is `sqlite:///./telemetry.db`. Set `DATABASE_URL` to a
PostgreSQL URL (prefer `postgresql+psycopg://...`) or an absolute SQLite URL to
change it. Run Alembic before serving traffic or seeding. The application never
creates or alters tables. Use `uv run alembic check` to check model/migration
drift. The initial migration's downgrade drops its telemetry tables, so test
downgrades only on disposable databases.

Use a single server process for the existing RobotState encoder. This increment
persists state and restores it at startup, but does not coordinate state
association across worker processes. SQLite execution and plans were verified
locally; PostgreSQL live execution was not verified. Inference submission and
completion perform short synchronous SQL transactions; operator read routes
and the purge loop run DB work off the event loop. Measure on the target
database before increasing traffic.

## HTTP contracts

- `GET /v1/detections`: optional `robot_id`, `class_label`, `min_confidence`
  (0–1 inclusive), `start` (inclusive), `end` (exclusive), `sort` (`desc`
  default, or `asc`), `limit` (20 default, 1–100) and `cursor`. Timestamps
  require a timezone. Result has `items`, page-local `count` and
  `next_cursor` (null at the end).
- Pass `next_cursor` unchanged and keep the filters and sort identical.
  The cursor encodes the last returned `(captured_at, id)` and query scope.
  A strict lexicographic seek plus one lookahead row avoids offset drift
  and makes equal timestamps unambiguous. The token is opaque by contract,
  unsigned and never used as authorization. Malformed or mismatched cursors
  return 422. This is live traversal, not a transaction snapshot: newer rows
  ahead of a descending cursor appear after refresh; late rows behind it
  can still appear; retention can remove rows.
- `GET /v1/robots/{robot_id}/timeline?start=...&end=...&bucket_seconds=3600`:
  a half-open interval up to 31 days, with UTC-aligned buckets of 60–86400
  seconds. Returns `robot_id`, `bucket_seconds`, and ascending occupied
  `items` with `start`, total `count` and `by_class`.
- `GET /v1/admin/stats`: process-local `data_quality` counters. They reset
  on restart; put this endpoint behind the deployment's operator access
  control. It is not itself an authentication boundary.

## Data quality and scheduled purge

Future timestamps return `FUTURE_TIMESTAMP`; older captures than
`MAX_CAPTURE_AGE_SECONDS` (86400 default) return `OLD_TIMESTAMP`.
Naive timestamps return `TIMESTAMP_TIMEZONE_REQUIRED`. Late captures behind
a robot's atomic persisted high watermark are accepted and counted because
telemetry can arrive late. The encoder still associates in completion order.
Invalid detection geometry or confidence and exact duplicates are counted
and omitted before persistence and association. Stored data has UTC binding,
foreign keys, SQL range and uniqueness checks. Use the read-only audit for
stored-data verification rather than scanning tables in the request path.

The purge job runs at startup and every `PURGE_INTERVAL_SECONDS` (30 default).
`PURGE_DRY_RUN=true` previews counts without deleting. Each run logs JSON
with its cutoff, mode and row counts by table. Exceptions are logged and the
job retries at the next interval. Per-platform TTL settings:
`FRAME_RETENTION_SECONDS`, `FARI_FRAME_RETENTION_SECONDS`,
`STATE_HISTORY_SECONDS`, `FARI_STATE_HISTORY_SECONDS`. The state history API
also applies `STATE_HISTORY_LIMIT` to its in-memory snapshots.

```sh
uv run python -m scripts.manage_telemetry audit
uv run python -m scripts.manage_telemetry purge
uv run python -m scripts.manage_telemetry purge --apply
```

## Synthetic data and query evidence

Use an isolated development database. The seed generator inserts multiple days
of spaced captures, mixed Aido/Fari robots, variable classes and confidence,
including empty frames. It also inserts lifecycle events and a recent snapshot
burst for each robot. No image files are generated. Counts and distributions
are reproducible with `--seed`; IDs get a fresh prefix per run. Synthetic
retention starts at import so old capture dates are queryable immediately.

```sh
export DATABASE_URL=sqlite:///./telemetry-demo.db
uv run alembic upgrade head
uv run python -m scripts.seed_telemetry --days 3 --robots 6 --frames-per-day 240
# Substitute the printed prefix and anchor:
uv run python -m scripts.explain_telemetry seed-EXAMPLE-00 2026-11-09T00:00:00Z
```

For dashboard demos longer than 60 seconds, run the development server with
`PURGE_DRY_RUN=true` or explicitly choose synthetic-data TTLs. Do not apply
those demo choices to production. The plan runner uses SQLite and runs
`ANALYZE` on the selected development database. The capture in this folder
covers all filter combinations, both directions and cursor continuations.
See [worked queries](W07_Query_Examples.md), the [data model](W07_Data_Model.md),
and the [seed run](W07_Seed_Run.json).

The automated tests migrate an isolated database and exercise the real API,
constraint failures, migration downgrade, combined filters, pagination
during insertion, timeline totals, quality checks and retention cascades.
