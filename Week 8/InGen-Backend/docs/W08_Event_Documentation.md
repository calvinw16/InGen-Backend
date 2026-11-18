# W08 event engine and webhook contract

From the Week 8 backend, run `uv sync --locked`, then
`uv run alembic upgrade head` and `uv run uvicorn app.main:app`.
Revision 0002 upgrades existing telemetry and preserves lifecycle events.

Set `OPERATOR_TOKEN` to a private value and send it in
`X-InGen-Operator-Token` for rule management, acknowledgements, subscriber
management and dead-letter inspection. These operations return 403 when no
token is configured. The actor is operator-supplied attribution, not a
verified individual identity. Deploy behind trusted network/access controls:
existing telemetry reads and the dashboard do not authenticate operators.

## Rule management and field reference

| Route | Behavior |
| --- | --- |
| GET /v1/rules | List rules, including disabled rules |
| POST /v1/rules | Create and return a rule with a generated ID (201) |
| PUT /v1/rules/{id} | Replace its definition and reset progress |
| POST /v1/rules/{id}/disable | Disable, retaining past events; reset progress |

| Field | Semantics |
| --- | --- |
| name | Nonempty operator-facing name, maximum 120 characters |
| enabled | Defaults to true |
| robot_id, platform | Optional scope; both must match when supplied. Robot ID is exact; platform is case insensitive. |
| class_labels | Nonempty set of exact detection labels |
| min_confidence | Inclusive [0,1] threshold, default 0.5 |
| zone | Optional normalized top-left x/y/w/h; the detection center must fall inside, including the edges |
| utc_window | Optional start/end UTC clock times without offsets. Start inclusive, end exclusive; inverted ranges span midnight. Uses capture time. |
| consecutive_frames | Integer 1–1000, default 1. Counts matching completed frames for this rule and robot, not individual boxes. |
| severity | info, warning (default), or critical |
| cooldown_seconds | Integer 0–86400, default 60. UTC elapsed time since the last alert for the rule and robot. |

The evaluator sees the cleaned detections and resulting RobotState on each
completed inference frame; its conditions use current observations rather
than stale tracked entities, and the result records the state version.
Progress is durable, separate by rule and robot. A completed frame without a
match, including an empty frame or a capture outside the time window, resets
the streak. Changing platform breaks the streak. Failed inference does not
count as an observation. Frames are processed in completion order, even if
they arrived with an older capture timestamp. The streak saturates at the
configured threshold. A continuously matching scene can alert again once
cooldown expires. Acknowledgement does not reset suppression.

The streak rejects isolated model noise; cooldown limits alerts from a
persistent scene. Firing on every frame would bury new incidents under
repeated copies. A streak does not prove the same physical object matched
across frames, or that continuous time elapsed between observations.

### Three worked rules

Submit each JSON object separately to `POST /v1/rules`. Example:

```sh
curl -sS http://localhost:8000/v1/rules \
  -H "X-InGen-Operator-Token: $OPERATOR_TOKEN" \
  -H 'Content-Type: application/json' -d @rule.json
```

**Patrol intrusion:** two person detections on successive completed frames
inside the patrol zone during the overnight UTC window.

```json
{"name":"Patrol intrusion","platform":"aido","class_labels":["person"],"min_confidence":0.8,"zone":{"x":0.1,"y":0.25,"w":0.7,"h":0.65},"utc_window":{"start":"22:00","end":"05:00"},"consecutive_frames":2,"severity":"critical","cooldown_seconds":300}
```

**Unattended vehicle candidate:** eight successive observations in a restricted
bay prompt manual review. This rule does not establish that the vehicle is
stationary, unattended, or the same vehicle throughout.

```json
{"name":"Unattended vehicle candidate","robot_id":"lot-rover","class_labels":["vehicle"],"min_confidence":0.75,"zone":{"x":0.55,"y":0.25,"w":0.4,"h":0.65},"consecutive_frames":8,"severity":"warning","cooldown_seconds":600}
```

**Fari interaction candidate:** a person observed in the interaction zone can
prompt review. This does not infer identity, consent, or interaction intent.

```json
{"name":"Fari interaction candidate","platform":"fari","class_labels":["person"],"min_confidence":0.9,"zone":{"x":0.25,"y":0.2,"w":0.5,"h":0.7},"consecutive_frames":2,"severity":"info","cooldown_seconds":120}
```

## Event query and acknowledgement

`GET /v1/events` returns `items`, page-local `count`, and `next_cursor`.
As with detections, use `robot_id`, `class_label`, `min_confidence`, `start`
(inclusive), `end` (exclusive), `sort=asc|desc`, `limit=1..100`, and
`cursor`. Defaults are descending order and 20 items. Event ranges and sort
use `occurred_at`; both timestamps require an offset. The stable key is
`(occurred_at,id)`. Reuse the same filters and sort on continuation pages.
Live pagination is not a transaction snapshot.

Additional filters are `rule_id`, `severity`, `kind`, and `acknowledged`.
Detection filters match a single triggering detection for alerts, or a detection
in the associated frame for lifecycle events. An event also exposes frame ID,
robot ID, platform, capture/occurrence timestamps, payload, and nullable rule,
severity and acknowledgement fields.

`POST /v1/events/{id}/acknowledge` accepts `{"actor":"Operator name"}`.
The first successful acknowledgement stores the actor and current UTC
timestamp. Repeats return the existing acknowledgement without overwriting it.
Unknown event IDs return 404.

## Subscriber and delivery contract

Configure `WEBHOOK_ALLOWED_URLS` as a JSON array of exact, normalized receiver
URLs. HTTPS is recommended; allow loopback HTTP only for local testing.
`POST /v1/webhook-subscribers` accepts `{"url":"https://receiver.example/alerts","secret":"<32 or more characters>"}`.
`GET /v1/webhook-subscribers` lists IDs and URLs without secrets. The server
compares allowed URLs at registration and at delivery; redirects and environment
proxies are disabled. Configure only trusted destinations, enforce deployment
egress controls, and protect the database and backups: secrets are stored
there so the worker can sign requests. Removing a URL from configuration
blocks subsequent sends to it after restart.

Only rule-generated alerts are sent; routine frame lifecycle rows remain
queryable. The transaction that writes the alert also writes one outbox row
per registered subscriber. The worker sends a JSON body shaped like:

```json
{
  "id": "event-uuid", "kind": "alert", "rule_id": "rule-uuid",
  "severity": "critical", "occurred_at": "2026-11-17T19:00:00+00:00",
  "frame_id": "frame-uuid", "robot_id": "demo-rover", "platform": "aido",
  "rule_name": "Patrol intrusion", "detection_ids": ["detection-uuid"],
  "state_version": 42
}
```

Verify the exact received bytes before parsing. For example:

```python
import hashlib
import hmac
import json

def verify_alert(raw_body: bytes, signature: str, secret: str) -> dict:
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected.encode("ascii"), signature.encode("utf-8")):
        raise ValueError("Invalid InGen signature")
    return json.loads(raw_body)
```

Pass the `X-InGen-Signature` header into this function. After verification,
deduplicate using the stable event ID or the `X-InGen-Delivery` ID. The latter
is stable per subscription delivery but is not covered by the signature; use
the signed event ID when a receiver depends on authenticated identity.
The signature does not independently prevent replay.

Outbound HTTP is performed outside the frame transaction, with a five-second
attempt deadline and a 30-second lease for crash recovery. Any non-2xx or
transport failure retries with exponential delay (base 1 second, capped at
30 seconds before 0.75–1.25× jitter). `WEBHOOK_MAX_RETRIES` counts retries after
the initial attempt, default four. After exhaustion, the outbox row moves
to the dead-letter table. `GET /v1/admin/dead-letters?limit=20` lists IDs,
failure time, attempt count and a reason without bodies or secrets. Delivery
can repeat if a sender stops after the receiver accepts but before the DB
records success. Event retention cascades to pending deliveries; dead-letter
metadata is retained for operator inspection and has no automatic purge in
this revision. Rule evaluation uses the existing single frame writer; this
increment does not make the RobotState service multi-process safe.
