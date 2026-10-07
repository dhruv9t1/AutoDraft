# Streaming Verification Checklist

End-to-end verification for the SSE streaming pipeline added to variable identification.

## Build & Setup

- [ ] **Backend compiles/tests clean**
  ```bash
  cd backend && python -m compileall -q app scripts tests && python -m pytest -q
  ```
  Expect: exit 0, no errors.

- [ ] **Frontend type-checks clean**
  ```bash
  cd word-extension && npx tsc --noEmit
  ```
  Expect: exit 0, no output.

- [ ] **Stop old backend, restart with new build**
  ```bash
  # Kill the running pid (or Ctrl-C its terminal)
  lsof -iTCP:3001 -sTCP:LISTEN
  cd backend && python run.py
  ```
  Expect Uvicorn on `http://127.0.0.1:3001`.

---

## Phase 1 — Backend SSE endpoint

- [ ] **New route reachable** — should NOT return 404 anymore
  ```bash
  curl -s -o /dev/null -w "HTTP=%{http_code}\n" \
    -X POST http://localhost:3001/api/documents/identify-variables-stream \
    -H "Content-Type: application/json" \
    -d '{"documentContent":"hello"}'
  ```
  Expect: `HTTP=200` (with body containing SSE events).

- [ ] **Empty body rejected**
  ```bash
  curl -s -o /dev/null -w "HTTP=%{http_code}\n" \
    -X POST http://localhost:3001/api/documents/identify-variables-stream \
    -H "Content-Type: application/json" \
    -d '{"documentContent":"   "}'
  ```
  Expect: `HTTP=400`.

- [ ] **Oversize body rejected** (> 5 MB)
  ```bash
  python3 -c "import json; print(json.dumps({'documentContent':'x'*6_000_000}))" | \
    curl -s -o /dev/null -w "HTTP=%{http_code}\n" \
      -X POST http://localhost:3001/api/documents/identify-variables-stream \
      -H "Content-Type: application/json" --data-binary @-
  ```
  Expect: `HTTP=413`.

- [ ] **First SSE frame arrives BEFORE total Ollama latency** — the whole point of streaming
  ```bash
  curl -N -X POST http://localhost:3001/api/documents/identify-variables-stream \
    -H "Content-Type: application/json" \
    -d '{"documentContent":"Cheque No. 123456 dated 03/03/2023, drawn on STATE BANK OF INDIA for Rs. 3,94,033 in favor of complainant Acme Corp at PIN 380006."}'
  ```
  Expect: events appear incrementally:
  ```
  event: chunk_done
  data: {"chunkIndex":0,"totalChunks":1,"variables":[...]}

  event: progress
  data: {"completed":1,"total":1}

  event: complete
  data: {"variables":[...],"identificationPercentage":...,"status":"success","message":null}
  ```
  **Watch the timestamps** — first `chunk_done` should land within `(Ollama-first-token + ~100ms)`, NOT at the end.

- [ ] **Multi-chunk doc emits multiple chunk_done events** — use a > 1 MB document
  ```bash
  # Generate a doc with multiple paragraphs to force chunking
  python3 -c "print(('Cheque No. 999 dated 01/01/2024 to ABC Co.\n\n' * 30000))" > /tmp/big.txt
  python3 -c "import json,sys; print(json.dumps({'documentContent': open('/tmp/big.txt').read()}))" | \
    curl -N -X POST http://localhost:3001/api/documents/identify-variables-stream \
      -H "Content-Type: application/json" --data-binary @- 2>&1 | grep "^event:"
  ```
  Expect: multiple `event: chunk_done` lines (one per chunk), several `event: progress` lines, one `event: complete` line.

- [ ] **Chunk failure does NOT abort stream** — induce one by setting an invalid `OLLAMA_API_KEY` for one chunk (or simulate via temporary code change). Should see `event: error` for the failed chunk and `event: complete` still fires.

- [ ] **KeepAlive prevents proxy idle-timeout** — leave the curl open against a slow Ollama call. Should see `: heartbeat` (SSE comment heartbeat) about every 10s.

- [ ] **Existing batch endpoint still works** (regression check)
  ```bash
  curl -s -X POST http://localhost:3001/api/documents/identify-variables \
    -H "Content-Type: application/json" \
    -d '{"documentContent":"Cheque No. 123456"}' | head -c 200
  ```
  Expect: JSON response with `variables`, `identificationPercentage`, etc. (no breakage from refactor of `validate_variables`).

---

## Phase 2 — Frontend streaming consumer

- [ ] **`supportsResponseStreaming()` returns true in browser**
  Open the dev server, open browser console:
  ```js
  // In Word add-in dev environment console
  typeof fetch !== "undefined" && typeof ReadableStream !== "undefined" && typeof TextDecoder !== "undefined"
  ```
  Expect: `true` (Edge WebView2 / modern Office).

- [ ] **SSE frame parser handles partial frames** — set a network throttle (DevTools → Network → Slow 3G) and run a stream. Logs should still show `chunk_done` events arriving cleanly. The buffer logic must reassemble across `read()` boundaries.

- [ ] **`onChunkDone` fires before `onComplete`** — log timestamps in the form's callbacks, confirm interleaving.

- [ ] **`onError` fires on bad status / dropped connection** — kill the backend mid-request, verify `onError` (not `onComplete`) is called and partial `found` array is preserved by the caller.

- [ ] **Fallback path works** — temporarily force `supportsResponseStreaming` to return false, confirm it polls the already-created `/api/documents/identify-jobs/{job_id}` job and the form still works end-to-end. Verify Ollama was not invoked a second time.

---

## Phase 3 — UI integration (TemplateCreationForm)

- [ ] **Live progress text renders** — open the form, click "Auto Detect Variables" on a multi-chunk doc. The loader should show:
  > Identifying fields… 7 found so far (chunk 2/4)
  Updating as each chunk completes. **Not** stuck on the static "Identifying fields in your document..." text the whole time.

- [ ] **`foundSoFar` increments monotonically** — should never decrease as chunks arrive.

- [ ] **`variableResponse` is set from `onComplete` (not from accumulated `found`)** — verify by checking that `variableResponse.variables.length` equals the deduped/sorted count, which may be **less than** the sum of all `chunk_done` batches if duplicates appeared at chunk boundaries.

- [ ] **Existing post-identification flow still runs** — `wrapVariablesWithBindingPlan`, `validateIdentificationAccuracy`, error banners — all behave the same as the batch path.

- [ ] **`streamProgress` clears on success AND on error** — after `setIsDetectingVariables(false)`, the progress text should not linger.

- [ ] **Edit-template flow unaffected** — `selectedTemplate` + `initialVariableResponse` path doesn't go through detection, so it should be untouched.

---

## Phase 4 — Production verification (after deploy)

- [ ] **nginx config updated** — verify `/etc/nginx/sites-available/<site>` has the new `location /api/documents/identify-variables-stream` block with:
  - `proxy_buffering off;`
  - `proxy_read_timeout 300s;`
  - `proxy_send_timeout 300s;`
  - `proxy_http_version 1.1;`
  - `chunked_transfer_encoding on;`

- [ ] **nginx config valid** — `sudo nginx -t` passes.

- [ ] **nginx reloaded** — `sudo systemctl reload nginx`.

- [ ] **Streaming works through nginx** — repeat the `curl -N` test against the production URL. **First frame must arrive incrementally**, not in one batch at the end. If batched, `proxy_buffering` is still on somewhere.

- [ ] **TLS cert / CORS still works** — open the production add-in in Word, confirm "Auto Detect Variables" streams (check Network tab: `EventStream` type, multiple events visible).

- [ ] **Ollama timeouts** — confirm `OLLAMA_TIMEOUT_SECONDS` in prod env ≥ 120, since streaming doesn't shorten Ollama latency, only perceived latency.

- [ ] **systemd service didn't break** — `systemctl status word-addin-backend` healthy after restart.

---

## Performance check

- [ ] **Perceived latency improved** — measure on a 4-chunk document:
  - **Before** (batch): time from "Auto Detect" click to first variable visible in UI
  - **After** (streaming): same measurement
  - Expect: streaming variant shows first variables in **~25–50%** of the batch time (because chunks complete in parallel and earliest one renders immediately).

- [ ] **No memory regression** — backend RSS shouldn't grow unbounded across 10+ streaming requests (`ps -o rss= -p <pid>` before/after).

- [ ] **No connection leak** — `lsof -p <backend-pid> | grep -c ESTABLISHED` returns to baseline after streams complete.

---

## Rollback plan

If streaming misbehaves in prod:

1. **Frontend toggle (no deploy needed):** comment out the `supportsResponseStreaming()` branch in `TemplateCreationForm.tsx` so it always uses `identifyVariables()`. Rebuild + redeploy `word-extension`.
2. **Backend route remains** — harmless unused code, no migration needed.
3. **nginx config** — leave the location block; `proxy_buffering off` only affects that one path.

---

## Sign-off

- [ ] All Phase 1 boxes ticked
- [ ] All Phase 2 boxes ticked
- [ ] All Phase 3 boxes ticked
- [ ] All Phase 4 boxes ticked
- [ ] Performance check confirms latency win
- [ ] Rollback plan understood

Verified by: __________ Date: __________
