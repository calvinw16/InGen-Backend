# W08 event engine delivery

The implementation is in `app/models/alerts.py`, `app/api/alerts.py`,
`app/services/alerts.py`, and `app/services/webhooks.py`. Migration 0002 adds
rules, per-rule/per-robot progress, subscriber registration, a durable outbox
and dead letters. It extends the existing events table without rewriting
the Week 7 migration.

Frame completion evaluates rules, stores events and queues notifications in
one database transaction. The HTTP worker claims committed deliveries with
short leases and runs separately from frame ingestion. See the
[rule and delivery contract](W08_Event_Documentation.md) for API examples and
the [dashboard guide](W08_Dashboard.md) for the live operator workflow.

Verification covers migration of existing lifecycle rows, frame streaks and
cooldown, event filtering and cursor pagination, first-write acknowledgement,
destination restrictions, signature bytes, retry deadlines and exhaustion.
The recorded demo uses a real loopback receiver and stub-backed JPEG input.
The database tests run on SQLite; live PostgreSQL was not exercised.
