# WORD-005 / WORD-006 / WORD-007 hardening

This consolidation pass implements the three Word binding integrity blockers from the v1.3 deep audit.

## WORD-005 — semantic/identity/location reconciliation

The embedded AutoDraft manifest is now schema version 2 and records each binding occurrence rather than only each tag. Each committed occurrence records:

- immutable AutoDraft binding ID;
- semantic/field identity;
- occurrence ID;
- exact Word content-control ID;
- expected AutoDraft-approved normalized text and current raw length;
- expected content-control title;
- source story/paragraph/table/header/footer coordinates and source offsets.

Reconciliation now detects missing controls, duplicate/copy-pasted tags, wrong Word control identity, unapproved text changes, title changes, missing integrity metadata, structural movement and old manifest schemas. Intentional AutoDraft edits update the embedded expected text/title evidence. Text-length changes also shift later recorded offsets in the same source paragraph so legitimate filling does not create false movement alarms.

## WORD-006 — transaction-owned rollback

Binding insertion no longer rolls back by final tag. Newly created controls receive a transaction-unique temporary tag before their first Word sync; their exact Word control IDs are captured immediately after creation. If a later operation fails, rollback deletes only controls whose exact ID or transaction-unique temporary tag belongs to that failed commit. Pre-existing duplicate final tags are not rollback targets.

## WORD-007 — deterministic occurrence selection

The live Word range resolver now uses the same strict semantics for both occurrence counting and `paragraph.search`:

- case-sensitive;
- punctuation-sensitive;
- whitespace-sensitive;
- no wildcard matching.

The grounded source offset must still contain the exact anchor. The selected Word range is re-read and compared with the immutable planned text before any content control is inserted. There is no permissive `Math.min` fallback to a different occurrence. Long and cross-paragraph bindings use exact start/end anchors and post-selection range verification.

## Validation in this build environment

- targeted TypeScript semantic check of the modified Word modules: pass (Office API stubbed only for type availability);
- TypeScript syntax transpilation of all modified files: pass;
- focused deterministic occurrence/location helper tests: pass;
- static assertions for WORD-005/006/007 invariants: pass.

A full clean `npm ci`/Vitest/webpack run and real Microsoft Word Windows/Mac host execution remain separate release gates; this environment could not complete dependency installation and cannot emulate Word's real host behavior.
