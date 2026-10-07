# AutoDraft v1.3 Gavel integration validation

Date: 2026-10-05

Baseline: the user-supplied `AutoDraft-v1.2-Clio-Integrated-2026-10-05.zip`.
Baseline SHA-256: `a6543720a30fc65fb4ef0a76e961f51cd876558ffcaa1d87e08d1a204ec3cdb6`.

## Scope implemented

- shared bounded/safe expression AST for conditions, calculations, formatting and repeater expressions;
- lazy `if`/`and`/`or`/`coalesce` evaluation so inactive branches cannot fail an otherwise valid workflow;
- immutable workflows/versions and internal/client version-pinned sessions;
- public workflow token bootstrap with SHA-256 token storage and tenant-context recovery;
- page/question conditions, reusable calculations, repeaters and nested repeaters;
- explicit lawyer-controlled workflow → canonical matter-data promotion;
- Word-authored conditional/repeating content-control regions through the centralized Word operation queue;
- editable versioned template-automation blueprints with a raw JSON editor that does not destroy temporarily-invalid text while typing;
- DOCX-package preflight before automation publication;
- headless DOCX rendering for one immutable template version or a published Document Set version;
- Selection → Population → actual headless Document Set generation → Review flow in the taskpane;
- generation artifact persistence and optional Matter Document capture with byte-size/checksum provenance;
- generation-run/workflow-session matter/version consistency checks;
- Gavel-focused taskpane workflow/template automation UI.

## Deliberate safety boundaries

- Workflow completion never silently promotes client answers into canonical matter data. An authenticated lawyer must explicitly apply a completed session.
- Promotion only targets existing active matter-scoped semantic Field Definitions; unknown keys are skipped and invalid typed values are reported.
- A Generation Run cannot be combined with a different matter, a different Document Set version, or an unrelated Workflow Session.
- Expressions cannot execute Python `eval`, arbitrary code, SQL, filesystem operations, or model calls.
- General workflow questions do not duplicate Intake's secure file-upload subsystem.

## Deliberate non-claims

- No production PDF converter is included; headless generation is DOCX only.
- Synthetic Open XML tests do not replace real Microsoft Word host validation.
- The sandbox does not provide a live disposable PostgreSQL server, Ollama daemon, OCRmyPDF/Tesseract runtime, or Microsoft Word host.

## Candidate archive / clean-room verification

The source tree was audited, packaged, the candidate ZIP was checked with `unzip -t`, then that exact archive was extracted to a new directory and the checks were repeated against the extracted bytes.

Results:

- backend compile/import: passed;
- backend pytest: **96 passed, 2 skipped**;
- the two skipped tests are the existing real-PostgreSQL environment gates;
- 16-fixture golden extraction corpus: **precision 1.000 / recall 1.000 / F1 1.000 / duplicate rate 0.000**;
- lawyer-firm candidate benchmark: **recall 1.000 / decided-case rule accuracy 1.000**;
- TypeScript source analysis: **0 unexpected/code-level diagnostic categories**; diagnostics were only TS2304/TS2307/TS2503/TS2580 caused by absent installed frontend/Office/Node declarations;
- `npm ci --offline`: unavailable because `yoctocolors-cjs@2.1.3` is not cached;
- a normal `npm ci` could not complete within the sandbox network window, so Vitest/webpack are not falsely claimed as run;
- source release audit: passed;
- candidate ZIP release audit: passed;
- clean-extraction release audit: passed;
- ZIP integrity: passed;
- candidate archive entries: **392**;
- forbidden release paths (`.env`, `.git`, `.venv`, `node_modules`, `__pycache__`, `.pytest_cache`): **0**.

The final release archive is rebuilt after this ledger is written and is re-extracted/rechecked before delivery.
