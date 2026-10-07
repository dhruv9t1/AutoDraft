# Jev / TypeSafe AI integration in AutoDraft 1.1

Status: optional provider implemented; disabled by default.

AutoDraft uses Jev only as a narrow **System-1 candidate decision provider**. It does not replace deterministic extraction, semantic field mapping, Qwen/System-2 reasoning, source grounding, binding validation, or lawyer review.

## Runtime position

```text
deterministic candidates
        ↓
rules
        ↓ (abstain/ambiguous)
optional Jev System-1
        ↓ (abstain/ambiguous)
Qwen System-2 semantic verification
        ↓
lawyer review when still uncertain
```

Jev classifies an already-observed candidate as `replaceable_value`, `static_text`, or `ambiguous`. Its score is stored only as diagnostic evidence. Conservative bands are applied by the provider, and the middle band remains ambiguous.

## Safety properties

- `SYSTEM1_PROVIDER=off` by default: no legal text is sent to the hosted provider unless the deployment owner enables it.
- The API key exists only in backend configuration, never in the Word bundle.
- Provider/network failure returns an abstention; it does not fail the whole AutoDraft request.
- Jev cannot auto-bind Word content controls directly.
- `needs_review` candidates are excluded independently by the backend wrapping plan and the frontend Word mutation pipeline.
- When System-2 is unavailable, candidate previews are explicitly review-only and the response remains `unavailable`.

## Configuration

```env
SYSTEM1_PROVIDER=off            # off | jev
JEV_API_URL=https://api.typesafe.ai/v1/systemone
JEV_API_KEY=
JEV_MODEL=jev-latest
JEV_TIMEOUT_SECONDS=20
```

The endpoint and model are configuration, not hard-coded deployment assumptions. Validate the configured provider contract against the actual TypeSafe account before enabling it in production.

## Why Jev does not name fields

“Is this span replaceable?” and “What legal fact does this span represent?” are different problems. AutoDraft keeps the first problem narrow for System-1 and leaves semantic naming/role mapping to rules/Qwen/lawyer review. This makes the layer replaceable and measurable.

## Evaluation

`backend/scripts/evaluate_candidates.py` exercises the same candidate engine and rules against checked-in candidate labels. Jev should be evaluated on held-out lawyer-reviewed examples before any deployment-specific threshold is changed.
