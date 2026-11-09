# Week 06 log

This increment extended the RobotState encoder with bounded history and checked
whether the perception contract can support Fari as well as Aido. The existing
current-state endpoint remains available. A new history endpoint returns the
last requested number of retained snapshots, ordered by version. Unknown robots
return empty history, and invalid query limits receive validation errors.

The encoder already used a lock, but concurrency required more than protecting
the entity dictionary. Version increments, aggregate counts, snapshot creation
and retention pruning now share the same critical section. Default timestamps
are sampled after acquiring the lock to avoid false backwards-time errors under
thread contention. The current worker serializes inference jobs, while the lock
also protects direct concurrent encoder callers. This remains a single-process
design; a multi-process deployment will require shared transactional storage or
a dedicated state owner.

The Fari review used the local Week-1 brief. It confirmed that normal raw video
should not be retained and that safety inference remains on the device. It also
identified an important distinction: Fari still produces continuous structured
health telemetry, even though visual requests and urgent event delivery have
different operational patterns. The current JPEG contract does not represent
clinical events, resident identity or consent.

The minimal implementation reused the existing platform discriminator instead
of introducing a competing field. Platform now appears in encoded state and
history. A policy hook selects shorter Fari retention for terminal frame records
and state snapshots. Decoded images are explicitly released when inference
finishes, including failures. The policy does not provide secure memory erasure,
authenticated platform assignment or a production deletion deadline. These
limits are documented rather than represented as completed privacy controls.

Verification includes simultaneous HTTP submissions from one robot and direct
multi-threaded writes to the encoder. Assertions cover unique ordered versions,
stable entity identity, observation counts, history isolation and expiration.
The documentation includes the state schema, concurrency approach, Fari gap
analysis and configuration defaults in Markdown with W06 filenames.

The next review should confirm platform registration rules, an event-envelope
contract and the deployment storage model. The evaluation rubric is supplied as
an unsigned review worksheet. No reviewer signature or confirmed future scope
has been fabricated.
