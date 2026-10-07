# FlatWrap Performance Optimization — Per-Variable Batching

## Problem

`wrapVariablesViaFlatText` takes ~240s for 115 variables / 542 hits against a
real legal document.

- `mapBuild` = 2,322 ms (negligible)
- `varLoop` = 237,847 ms (**~99% of time**)

`context.sync()` is the bottleneck. Current flow queues Word API calls per-hit
and syncs 2–3 times **per hit** (search, parent-check, insert/format). With
542 hits this creates ~1,500 round-trips across the Word JS API bridge.

## Fix

Batch all Word API operations **per variable** instead of per hit. Reduce sync
calls per variable from `O(hits)` to exactly **3**.

## Design

For a single variable with N flat-text hits:

1. **Compute** (pure JS, no sync) — for each hit, compute start/end
   paragraphs, search text / anchors.
2. **Phase A — Search** — queue all `search()` calls for every hit,
   `load("items")` on every `RangeCollection`, then ONE `await context.sync()`.
3. **Phase B — Resolve** (pure JS) — from loaded results, pick the correct
   `Word.Range` (single-paragraph `search` pick, or cross-paragraph
   `expandTo`).
4. **Phase C — Parent check** — for all resolved ranges, queue
   `parentContentControlOrNullObject.load("isNullObject")`, then ONE sync.
5. **Phase D — Insert & format** — for ranges whose parent is null,
   queue `insertContentControl()`, set tag/title/appearance/color, apply font
   formatting. Then ONE sync.
6. **Phase E — Track** (pure JS) — update `wrappedIntervals` and stats.

The in-memory `wrappedIntervals` pre-filter remains in place **before Phase A**,
so hits that are already inside a previously wrapped interval are skipped
without any Word API round-trip.

The per-variable `existingTags` pre-check also remains.

## Backward compatibility

- Keep `rangeFromGlobalOffsets()` unchanged (it may be called from other code
  or used in future features). It remains the single-hit async API.
- Keep all exported pure-JS helpers (`findAllVariableInFlatText`,
  `buildNormalizedView`, `countOccurrencesBefore`, etc.) unchanged.
- Keep the `WrappingStats` interface unchanged.

## File Changes

- `word-extension/src/services/wrappingPipeline.ts`
  - Modify `wrapVariablesViaFlatText` — replace per-hit serial loop with
    per-variable batched phases.
  - Introduce two new **internal** pure-JS helpers to keep the function
    readable:
    - `buildVariableSearchTasks(map, hits)` — converts flat-text hits into
      search-task metadata (paragraph refs, anchor strings, occurrence
      counters, etc.). No Word API calls.
    - `resolveRangeFromTask(task, singleResults, startResults, endResults)` —
      given loaded `RangeCollection`s, returns the final `Word.Range | null`.
      Handles single-paragraph pick-by-occurrence and cross-paragraph
      `expandTo`.

## Edge cases handled

- **All hits already blocked by `wrappedIntervals`** → zero syncs.
- **No hits in flat text** → zero syncs.
- **All searches miss** → one sync in Phase A only.
- **All ranges have non-null parent CC** → two syncs (Phase A + C).
- **Cross-paragraph `expandTo` throws** → counted as `missedRange`.
- **Variable with 1 hit** → still 3 syncs (no worse than current path).
- **Zero-length or empty `originalText`** → handled by existing early-return.

## Expected outcome

- Sync count drops from `~1,500` to `~3 × active-variable-count ≈ 345`.
- Expected wrapping time drops from **~240s → ~50–70s** (≈4× speedup).

## Verification

- Run existing unit tests: `cd word-extension && npm run test`
- Run existing integration tests (pure functions).
- Build passes: `cd word-extension && npm run build`
- Lint passes: `cd word-extension && npm run lint`
