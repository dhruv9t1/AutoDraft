# Prompt-Eval Scripts (Node-only)

These scripts measure the variable-identification prompt in `backend/src/ollama.rs`. They run **outside** the Word add-in bundle — never import them from `word-extension/src/`, the API key would leak to the client and the bundle would balloon.

## Files

```
scripts/
├── eval-variable-identification.ts       Main harness (one row per fixture)
├── eval-fixtures/variables/*.json        Test cases — see "Fixture format" below
└── eval-results/results-<version>.json   Persisted per-version scores
```

## Setup (one-time)

```bash
cd word-extension
npm install -D tsx @anthropic-ai/sdk
```

`tsx` runs `.ts` files directly without a build step. `@anthropic-ai/sdk` is only needed when the model grader is enabled (see `EVAL_SKIP_MODEL_GRADER=1` to skip it).

## Run

```bash
# Backend must be running on localhost:3001 (or set EVAL_BACKEND_URL).
# ANTHROPIC_API_KEY is required unless EVAL_SKIP_MODEL_GRADER=1.

cd word-extension
ANTHROPIC_API_KEY=sk-ant-... npx tsx scripts/eval-variable-identification.ts v1
```

The argument (`v1`) labels this run; the results land in `eval-results/results-v1.json`. After tweaking the prompt in `backend/src/ollama.rs`, re-run with a new label (`v2`, `v3`, …) and **diff the per-row results** to see what improved or regressed.

```bash
# Code graders only — fastest, free, no API key needed
EVAL_SKIP_MODEL_GRADER=1 npx tsx scripts/eval-variable-identification.ts v2
```

## What gets scored

Per the `prompt-evaluation` skill, code graders run on every row (cheap, deterministic). The model grader is only used for the one dimension code can't judge — naming quality.

| Dimension | Type | Targets |
|---|---|---|
| `verbatim` | code | % of returned `originalText` that's a literal substring of the input doc — catches AI hallucination + paraphrasing |
| `noOverlap` | code | 0/10 — penalizes any returned `originalText` that's a substring of another |
| `noListMarkers` | code | 0/10 — penalizes layout-artifact rows like `[1]`, `(2)` |
| `noDuplicates` | code | 0/10 — penalizes the same span returned under multiple variable names |
| `recall` | code | % of `expected` rows from the fixture actually returned |
| `naming` | model | 1–10 — subjective: standard legal terminology, specific over generic, consistent |

Dimensions are **kept separate** — averaging them would let a perfect "no list markers" score mask a recall regression.

## Fixture format

Each `.json` in `eval-fixtures/variables/` looks like:

```json
{
  "name": "human-readable label (used in logs and reports)",
  "document": "Full plaintext of the document, escaping newlines as \\n",
  "expected": [
    { "name": "Reference Number", "originalText": "411/2026" },
    { "name": "Cheque Number",    "originalText": "000129" }
  ]
}
```

Tips for building a useful dataset (per the skill):

- **10–50 fixtures.** 3 is too noisy.
- **Mix the failure modes** you've seen in production: substring overlap, abbreviation paraphrasing, hallucinated values, list markers, etc. If every fixture is the same shape, you're testing one narrow capability.
- **Use real documents** when you can (sanitize PII first). Toy fixtures teach toy behavior.
- **Be honest about expected.** Only list values you genuinely consider valuable variables — gaming `expected` to make the score go up defeats the point.

The starter file `sample-cheque-bounce.json` exercises three of the four failure modes from the recent logs (list markers, substring overlap risk via `Mr.` prefix, branch-name verbatim). Drop more real fixtures alongside it.

## Iteration loop

1. Record a baseline against the current prompt: `npx tsx scripts/eval-variable-identification.ts v1`.
2. Edit `build_system_prompt()` (or `build_user_prompt()`) in `backend/src/ollama.rs`. **Change one technique at a time** so you can attribute the score change.
3. Restart the Python backend (`cd backend && python run.py`).
4. Re-run with a new label: `npx tsx scripts/eval-variable-identification.ts v2`.
5. Diff per-row:

   ```bash
   diff <(jq '.results[] | {fixture, code}' eval-results/results-v1.json) \
        <(jq '.results[] | {fixture, code}' eval-results/results-v2.json)
   ```

6. If the average plateaus, look at the lowest-scoring rows in v2 — their failure mode is what your next prompt edit should target.
