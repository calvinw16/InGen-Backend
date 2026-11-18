# Week 08 log

This increment turned incoming perception observations into alerts that an
operator can review and acknowledge. Rules are stored as data, so changing
the expected object class, region, UTC schedule, or alert severity does not
require a code deployment. The rule engine evaluates each completed frame
alongside the updated robot state. It stores the rule identifier, the
triggering detection identifiers, and the state version so an operator can
trace an alert back to the observations that produced it.

The most useful suppression rule in the demo was the patrol rule: require
three consecutive person matches in the patrol zone, then allow at most one
alert per robot for 120 seconds. The first two frames both appeared in the
detections panel, but neither generated an alert. The third frame reached the
threshold and created one critical event. Further matching frames continued
to update the robot state and detections without creating another alert or
webhook. A missed match would reset the streak. This separates a short model
glitch from an incident worth reviewing and prevents a persistent incident
from crowding out new ones.

Delivery uses a durable outbox. The alert and its delivery jobs are committed
with frame completion, while HTTP requests run separately. A slow receiver
therefore cannot hold the ingestion path open. Each attempt signs the exact
body bytes with HMAC-SHA256. Receivers can authenticate the message before
parsing, and should deduplicate by its stable event ID because a crash can
cause a repeat delivery. Retries are bounded and backed off; permanently
failed attempts leave an inspectable dead-letter record.

The browser view uses the existing query conventions and plain HTML, CSS
and JavaScript. It polls for detections, current robot state, and active
alerts, and sends its time range to the API. The recording exercises a real
local server with synthetic frames and a separate signature-verifying receiver.
Acknowledgement persists the first operator and timestamp; it is independent
of the cooldown so acknowledging an alert cannot immediately recreate it.
The remaining deployment work is to verify the database migration on live
PostgreSQL and set appropriate access, secret storage, and egress controls.
