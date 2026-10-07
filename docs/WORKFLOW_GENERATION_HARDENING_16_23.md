# Workflow / Generation correctness hardening — issues 16–23

This release hardens the remaining workflow-calculation and generation-attempt correctness boundaries.

## Calculation namespace and dependencies

- Top-level workflow answer semantic keys are globally unique.
- Workflow questions may not use the reserved `calculated.` output namespace.
- Calculation keys may not collide with answer keys.
- Calculation-to-calculation references must use `{ "var": "calculation.key" }`; using `field`/`fact` for another calculation is rejected.
- Unknown calculation variables, self/cyclic dependencies, and cycles are rejected at workflow-definition validation time.
- Calculations are topologically ordered before evaluation, so forward references do not depend on authoring order.
- Stored calculation results remain separate from answer/canonical values. Generation exposes them only as `calculated.<key>`.

## Expression ordering

`gt`, `gte`, `lt`, and `lte` are fail-closed. They support numeric values and ISO date/datetime values; malformed values do not fall back to lexicographic string ordering.

## Repeater and render bounds

Workflow answer validation enforces a per-repeater platform maximum and a cumulative repeated-item budget, even when a workflow author omits `maxItems`. The DOCX renderer independently enforces per-repeater, cumulative repeated-item, content-control, XML, uncompressed-package, and final compressed-output limits.

## Generation idempotency and attempt history

Every persisted headless generation request requires an idempotency key. The idempotency key protects the request identity, while each execution is represented by its own `generation_attempts` row.

Retries:

- never overwrite a failed/stale attempt;
- create a new attempt with `retry_of_attempt_id` and monotonically increasing `attempt_number`;
- record `started_at`, `finished_at`, status, error, artifact IDs, and response metadata;
- make terminal attempts immutable at the database layer;
- replay the completed attempt for the same idempotency key/fingerprint;
- preserve all generation-run artifact IDs and generation-attempt IDs instead of replacing run history.

DOCX rendering continues to execute outside the short persistence transaction; only verified rendered results are committed.
