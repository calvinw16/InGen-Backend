# W06 Fari generalisation and gap analysis

The existing frame and state contract can serve a small Fari perception request,
but it cannot represent Fari's clinical event platform. This change propagates
the existing platform discriminator into encoded state and history, and adds
shorter platform-specific retention defaults for derived records. It preserves
Aido's asynchronous frame path while reducing retention for Fari observations.

## Evidence and interpretation

The local Week-1 source is `Week 1/InGen-Backend/docs/Fari.docx`. It describes
close-range RGB-D sensing, local recognition on Jetson Orin NX, and zero routine
video retention: raw visual inputs are processed and discarded. It also describes
continuous structured health telemetry at 10 Hz, with urgent clinical events
requiring a separate low-latency path. Therefore “event-driven rather than
continuous” applies to backend visual requests and event routing, not to an
absence of continuous telemetry. The source does not specify a 60-second derived
state retention period; that value is a configurable conservative engineering
default introduced here, not an attributed requirement or compliance claim.

## What generalises and what does not

| Existing field or behavior | Fari assessment |
| --- | --- |
| robot_id | Useful device identity, but not a resident, patient or consent identity |
| platform | Already required in frame input/metadata; now carried to state and history |
| timestamp and frame IDs | Useful correlation, but not an event ID, event type or idempotency key |
| JPEG image_base64 and 2 MiB cap | Useful optional visual request; mandatory JPEG excludes structured events, depth and health observations |
| Normalized image-space bounding box | Reusable for visible entities; cannot express depth, physical distance or patient location |
| person/vehicle/bicycle/animal/obstacle labels | Model grouping favors rover scenes; does not encode falls, identity, expression, vitals or clinical severity |
| Temporal center-distance association | Useful short-lived scene memory; cannot guarantee identity across occlusion, camera motion or separate event episodes |
| observation_count and state_version | Reusable progression fields; not a clinical audit or exactly-once event delivery guarantee |
| POST then GET polling | Supports asynchronous perception, not urgent push alerts or offline safety decisions |

No field literally requires Aido by name. The rover assumptions are embedded in
mandatory RGB JPEGs, the class vocabulary, image-space positions and ongoing
cross-frame association. Renaming robot_id would not address those gaps.

## Minimal implemented change

Frame.platform now flows into RobotState and every history snapshot. A platform
policy hook selects frame metadata and state-history TTLs: Fari defaults to
60 seconds for each, other platforms to 3600 seconds. History also has a bounded
snapshot count. A platform switch resets association and history so objects are
not silently joined across different platform contexts; robot version numbers
continue increasing. Raw imagery is never archived; decoded images are explicitly
released by the inference thread after use. Existing clients retain the required
platform field and gain an additive state field and a history endpoint.

This closes the most immediate contract/retention gap without adding a pretend
clinical schema. Frame-record expiration removes metadata and detections; it does
not claim that historical snapshots or active entities expire on the same timer.
Current entities keep their separate 5-second stale and 30-second eviction rules.
Policies are selected from client-provided platform strings, so this is a hook,
not an authenticated privacy boundary. Device registration should eventually bind
platform to identity and prevent a Fari client selecting the default policy.

## Deferred requirements and reasons

Close-range recognition needs task-specific models and labeled evaluation; the
COCO detector is not evidence of fall, face or emotion recognition performance.
An event envelope with event_id, event_type, occurred_at and optional observation
payload is deferred until event semantics and retry/idempotency requirements are
agreed. FHIR resources, resident identity, consent enforcement, role-based access,
encryption, audit storage and urgent push delivery need dedicated contracts and
infrastructure. They are not implemented by adding arbitrary optional fields.

Retention cleanup is lazy on access, and state is volatile and process-local.
Production privacy needs timed deletion, authenticated policies, controlled logs,
and management of request buffers and model-library memory. This change provides
no clinical deployment or privacy-compliance guarantee. Safety decisions remain
on the robot as the Week-1 brief requires.

Tests exercise Fari platform propagation, shorter retention, expired-frame 404s,
history pruning and concurrent state consistency. They verify contract mechanics,
not clinical recognition accuracy, alert deadlines or healthcare compliance.
