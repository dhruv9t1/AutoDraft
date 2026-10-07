from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator

import httpx

from .config import Settings
from .errors import (
    AIModelUnavailable,
    AIOutputInvalid,
    AIProviderUnavailable,
    AIRequestTimeout,
)
from .identification_mode import (
    IdentificationMode,
    classify_document,
    coverage_warnings,
    prompt_for_mode,
)
from .models import CandidateEvidenceModel, Variable
from .extraction.candidate_engine import generate_candidates
from .ai.decision import CandidateDecisionRouter, JevDecisionProvider, RulesDecisionProvider
from .post_processing import finalize, normalize, semantic_family

log = logging.getLogger(__name__)

JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["variables"],
    "properties": {
        "variables": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["variableName", "originalText", "position", "confidenceScore"],
                "properties": {
                    "variableName": {"type": "string"},
                    "originalText": {"type": "string"},
                    "position": {"type": "integer"},
                    "confidenceScore": {"type": "number"},
                },
            },
        }
    },
}

READINESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ok"],
    "properties": {"ok": {"type": "boolean"}},
}

FIELD_VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["decisions"],
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["index", "classification"],
                "properties": {
                    "index": {"type": "integer"},
                    "classification": {
                        "type": "string",
                        "enum": ["field", "static_text", "heading", "label", "ambiguous"],
                    },
                    "suggestedLabel": {"type": ["string", "null"]},
                },
            },
        }
    },
}

FIELD_VERIFY_SYSTEM = """You are AutoDraft's second-stage reusable-field verifier.
You receive already-grounded candidate spans from an arbitrary document. Decide what each highlighted candidate is; do not invent new spans.

Definitions:
- field: instance-specific VALUE that would normally change when this document is reused for another person, organisation, matter, transaction, application, event, project, period, or recipient.
- static_text: boilerplate, narrative, descriptive prose, fixed wording, or a fact that is part of the document's permanent content rather than a reusable slot.
- heading: section title or structural heading.
- label: caption/key that names a value but is not itself the value.
- ambiguous: there is not enough local context to decide safely.

Important:
- A date, number, email, URL, name, organisation, amount, qualification, location, or identifier is NOT automatically a field. Context decides.
- Do not classify headings or labels as fields merely because their wording could theoretically vary.
- Prefer coherent values, not fragments cut out of a larger value.
- You may suggest a concise user-facing label, but you must not alter original source text.
- Return one decision for every supplied index and only the required JSON object."""


class OllamaService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=settings.ollama_timeout_seconds)
        self.sem = asyncio.Semaphore(max(1, settings.ollama_max_parallel_chunks))
        self.readiness: dict[str, Any] = {
            "reachable": False,
            "modelAvailable": False,
            "model": settings.ollama_model,
            "error": "Not checked yet",
        }
        self.jev = JevDecisionProvider(
            endpoint=settings.jev_api_url,
            api_key=settings.jev_api_key if settings.system1_provider.strip().lower() == "jev" else "",
            model=settings.jev_model,
            timeout_seconds=settings.jev_timeout_seconds,
        )

    async def close(self) -> None:
        await self.client.aclose()
        await self.jev.close()

    async def check_readiness(self, *, probe: bool = True) -> dict[str, Any]:
        """Verify provider reachability, configured model, and structured output."""
        url = self.settings.ollama_api_url.rstrip("/") + "/api/tags"
        headers: dict[str, str] = {}
        if self.settings.ollama_api_key:
            headers["Authorization"] = f"Bearer {self.settings.ollama_api_key}"
        wanted = self.settings.ollama_model
        try:
            response = await self.client.get(
                url, headers=headers, timeout=min(30, self.settings.ollama_timeout_seconds)
            )
            response.raise_for_status()
            payload = response.json()
            installed: set[str] = set()
            for item in payload.get("models", []) if isinstance(payload, dict) else []:
                if not isinstance(item, dict):
                    continue
                for key in ("name", "model"):
                    value = item.get(key)
                    if value:
                        installed.add(str(value))
            aliases = {wanted}
            if ":" not in wanted:
                aliases.add(wanted + ":latest")
            available = bool(installed.intersection(aliases))
            structured = False
            error: str | None = None
            if not available:
                error = (
                    f"Configured Ollama model '{wanted}' is not installed. "
                    f"Installed models: {', '.join(sorted(installed)) or '(none)'}. "
                    f"Run: ollama pull {wanted}"
                )
            elif probe:
                try:
                    probe_result = await self._call(
                        'Return exactly an object with ok=true.',
                        'You are a health probe. Follow the supplied JSON schema.',
                        READINESS_SCHEMA,
                        model=wanted,
                    )
                    structured = probe_result.get("ok") is True
                    if not structured:
                        error = "Configured model did not pass the structured-output readiness probe."
                except Exception as exc:
                    error = f"Structured-output probe failed: {exc}"
            else:
                structured = available
            self.readiness = {
                "reachable": True,
                "configuredModel": wanted,
                "modelAvailable": available,
                "structuredOutput": structured,
                "ready": bool(available and structured),
                "model": wanted,
                "installedModels": sorted(installed),
                "error": error,
            }
        except httpx.TimeoutException as exc:
            self.readiness = {
                "reachable": False,
                "configuredModel": wanted,
                "modelAvailable": False,
                "structuredOutput": False,
                "ready": False,
                "model": wanted,
                "error": f"Ollama readiness check timed out: {exc}",
            }
        except Exception as exc:
            self.readiness = {
                "reachable": False,
                "configuredModel": wanted,
                "modelAvailable": False,
                "structuredOutput": False,
                "ready": False,
                "model": wanted,
                "error": f"Could not reach Ollama at {url}: {exc}",
            }
        return self.readiness

    def chunks(self, document: str) -> list[tuple[str, int]]:
        size = max(1000, self.settings.ollama_chunk_size)
        if len(document) <= size:
            return [(document, 0)]

        overlap = min(1200, max(400, size // 8))
        out: list[tuple[str, int]] = []
        start = 0
        while start < len(document):
            target = min(len(document), start + size)
            end = target
            if target < len(document):
                ws = max(start + size // 2, target - 900)
                cut = max(document.rfind("\n", ws, target), document.rfind(". ", ws, target))
                if cut > start:
                    end = cut + 1
            out.append((document[start:end], start))
            if end >= len(document):
                break
            start = max(start + 1, end - overlap)
        return out

    async def _deterministic(
        self,
        document: str,
        mode: IdentificationMode,
        boilerplate_values: set[str] | None = None,
        *,
        allow_external_system1: bool = False,
    ) -> list[Variable]:
        """Run the lawyer-firm-inspired candidate pipeline before System-2 Qwen.

        Candidate generation is deterministic and offset-safe. Rules and optional
        Jev may reject obvious static/boilerplate text, but uncertain items are kept
        for Qwen/lawyer review rather than silently discarded.
        """
        candidates = generate_candidates(document, mode)
        providers = [RulesDecisionProvider(boilerplate_values)]
        if allow_external_system1 and self.jev.enabled:
            providers.append(self.jev)
        await CandidateDecisionRouter(providers).decide_all(candidates)

        variables: list[Variable] = []
        for candidate in candidates:
            if candidate.review_state == "rejected":
                continue
            reason_codes = [e.code for e in candidate.evidence]
            variables.append(
                Variable(
                    name=candidate.suggested_label or "Variable",
                    originalText=candidate.original_text,
                    position=candidate.position,
                    confidenceScore=candidate.confidence,
                    candidateId=candidate.candidate_id,
                    candidateKind=candidate.kind,
                    candidateGroupId=candidate.group_id,
                    variants=candidate.variants,
                    repetitionCount=candidate.repetition_count,
                    classification=candidate.classification,
                    decisionSource=candidate.decision_source,
                    reviewState=candidate.review_state,
                    reasonCodes=reason_codes,
                    candidateEvidence=[
                        CandidateEvidenceModel(code=e.code, detail=e.detail, weight=e.weight)
                        for e in candidate.evidence
                    ],
                )
            )
        return finalize(variables, document)

    @staticmethod
    def _scope(chunk: str, offset: int, variables: list[Variable]) -> list[Variable]:
        return [v for v in variables if offset <= v.position < offset + len(chunk)]

    @staticmethod
    def _scope_known(chunk: str, known: list[Variable]) -> list[Variable]:
        lower = chunk.lower()
        return [v for v in known if v.original_text and v.original_text.lower() in lower]

    def _user_prompt(
        self,
        chunk: str,
        anchors: list[Variable],
        known: list[Variable],
        mode: IdentificationMode,
    ) -> str:
        a = "\n".join(f"- {v.name}: {v.original_text}" for v in anchors[:160]) or "(none)"
        k = "\n".join(f"- {v.name}: {v.original_text}" for v in known[:80]) or "(none)"
        return f"""Mode: {mode.value.upper()}
Perform full-coverage candidate extraction. Deterministic anchors are CANDIDATES, not guaranteed final fields; known variables are hints only.
For every returned item, originalText must be copied exactly from the document chunk and position should point to that occurrence inside the supplied chunk whenever possible.
<deterministic_anchors>
{a}
</deterministic_anchors>
<known_variables>
{k}
</known_variables>
<document>
{chunk}
</document>
Return only JSON."""

    @staticmethod
    def _recovery_prompt(
        chunk: str,
        first: list[Variable],
        mode: IdentificationMode,
    ) -> str:
        found = "\n".join(
            f"- {v.name} => {v.original_text.replace(chr(10), ' ')}" for v in first[:220]
        )
        if mode == IdentificationMode.LEGAL:
            focus = (
                "matter-specific parties, roles, addresses, dates/deadlines, court/case/police "
                "references, cheque/bank/account fields, transaction identifiers, amounts, "
                "business IDs, signing data and unfamiliar labelled VALUES"
            )
        else:
            focus = (
                "instance-specific values that genuinely change when the document is reused; "
                "exclude section headings, labels/captions, generic prose, instructions, and "
                "static descriptive text"
            )
        return f"""COVERAGE AUDIT ({mode.value.upper()}). Re-read every line and return ONLY missed reusable VALUES. Focus on {focus}.
<already_found>
{found}
</already_found>
<document>
{chunk}
</document>
If none return {{"variables":[]}}."""

    async def _call(
        self,
        user_prompt: str,
        system_prompt: str,
        schema: dict[str, Any] | str = JSON_SCHEMA,
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        url = self.settings.ollama_api_url.rstrip("/") + self.settings.ollama_api_path
        headers = {"Content-Type": "application/json"}
        if self.settings.ollama_api_key:
            headers["Authorization"] = f"Bearer {self.settings.ollama_api_key}"

        body: dict[str, Any] = {
            "model": model or self.settings.ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "temperature": self.settings.ollama_temperature,
            "top_p": self.settings.ollama_top_p,
            "top_k": self.settings.ollama_top_k,
            "seed": self.settings.ollama_seed,
            "format": schema,
            "options": {"num_predict": 8192, "num_ctx": 32768},
        }
        think = self.settings.ollama_think_level.lower()
        if think in {"on", "true"}:
            body["think"] = True
        elif think in {"high", "medium", "low"}:
            body["think"] = think

        last: Exception | None = None
        for attempt in range(self.settings.ollama_max_retries + 1):
            try:
                async with self.sem:
                    resp = await self.client.post(url, headers=headers, json=body)
                if resp.status_code == 404:
                    raise AIModelUnavailable(
                        f"Ollama could not load model '{body['model']}'. Run: ollama pull {body['model']}"
                    )
                resp.raise_for_status()
                raw = resp.json()
                content = (
                    (((raw.get("choices") or [{}])[0].get("message") or {}).get("content"))
                    or ((raw.get("message") or {}).get("content"))
                    or raw.get("content")
                    or raw.get("response")
                    or ""
                )
                try:
                    return self._parse_json_content(content)
                except (ValueError, json.JSONDecodeError) as exc:
                    raise AIOutputInvalid(str(exc)) from exc
            except AIModelUnavailable:
                raise
            except httpx.TimeoutException as exc:
                last = AIRequestTimeout(f"AI request timed out: {exc}")
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                last = AIProviderUnavailable(f"Could not reach Ollama: {exc}")
            except AIOutputInvalid as exc:
                last = exc
            except httpx.HTTPStatusError as exc:
                last = AIProviderUnavailable(
                    f"Ollama returned HTTP {exc.response.status_code}."
                )
            except Exception as exc:
                last = AIProviderUnavailable(f"AI request failed: {exc}")
            if attempt < self.settings.ollama_max_retries:
                await asyncio.sleep(2**attempt)
        if isinstance(last, Exception):
            raise last
        raise AIProviderUnavailable("AI request failed after retries.")

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        text = (content or "").strip()
        fence = chr(96) * 3
        if text.startswith(fence):
            text = re.sub(r"^.{3}(?:json)?\s*", "", text, flags=re.I)
        if text.endswith(fence):
            text = text[:-3].rstrip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            a, b = text.find("{"), text.rfind("}")
            if a < 0 or b <= a:
                raise
            parsed = json.loads(text[a : b + 1])
        if not isinstance(parsed, dict):
            raise ValueError("Structured model output must be a JSON object")
        return parsed

    @staticmethod
    def _all_occurrences(chunk: str, text: str) -> list[tuple[int, str]]:
        """Return grounded occurrences while preserving the exact document spelling."""
        if not text:
            return []
        out: list[tuple[int, str]] = []
        start = 0
        while True:
            idx = chunk.find(text, start)
            if idx < 0:
                break
            out.append((idx, text))
            start = idx + 1
        if out:
            return out

        lower_chunk, lower_text = chunk.lower(), text.lower()
        start = 0
        while True:
            idx = lower_chunk.find(lower_text, start)
            if idx < 0:
                break
            out.append((idx, chunk[idx : idx + len(text)]))
            start = idx + 1
        if out:
            return out

        # Last safe grounding tier: whitespace tolerant. This still returns an exact
        # substring from the supplied chunk; no fuzzy/edit-distance invention occurs.
        parts = [re.escape(x) for x in re.split(r"\s+", text.strip()) if x]
        if not parts:
            return []
        rx = re.compile(r"[\s\u00a0]+".join(parts), re.I)
        return [(m.start(), m.group(0)) for m in rx.finditer(chunk)]

    @classmethod
    def _anchor_llm_vars(cls, raw: dict[str, Any], chunk: str, offset: int) -> list[Variable]:
        """Ground model candidates to the intended source occurrence.

        Older code always chose chunk.find(text), which silently bound repeated values
        to the first occurrence. We now respect a valid model position when possible
        and otherwise choose the occurrence nearest to the returned position.
        """
        out: list[Variable] = []
        items = raw.get("variables", []) if isinstance(raw, dict) else []
        if not isinstance(items, list):
            return out

        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                name = str(item.get("variableName") or item.get("name") or "Variable").strip()
                text = str(item.get("originalText") or "")
                if not name or not text.strip():
                    continue

                occurrences = cls._all_occurrences(chunk, text)
                if not occurrences:
                    continue

                raw_position = item.get("position")
                position: int | None
                try:
                    position = int(raw_position)
                except (TypeError, ValueError):
                    position = None

                # Support providers that return either chunk-relative or document-absolute
                # positions. The prompt asks for relative positions, but this defensive
                # handling avoids selecting the first duplicate if a provider differs.
                target_local: int | None = None
                if position is not None:
                    if 0 <= position < len(chunk):
                        target_local = position
                    elif offset <= position < offset + len(chunk):
                        target_local = position - offset

                if target_local is None:
                    local, actual = occurrences[0]
                else:
                    local, actual = min(occurrences, key=lambda pair: abs(pair[0] - target_local))

                try:
                    conf = float(item.get("confidenceScore", 0.9))
                except (TypeError, ValueError):
                    conf = 0.9
                if conf > 1:
                    conf /= 100

                out.append(
                    Variable(
                        name=name,
                        originalText=actual,
                        position=offset + local,
                        confidenceScore=max(0.0, min(1.0, conf)),
                    )
                )
            except Exception:
                continue
        return out

    @staticmethod
    def _verification_context(document: str, variable: Variable, radius: int = 220) -> str:
        start = max(0, variable.position - radius)
        end = min(len(document), variable.position + len(variable.original_text) + radius)
        prefix = document[start : variable.position]
        suffix = document[variable.position + len(variable.original_text) : end]
        return f"{prefix}<<<CANDIDATE>>>{variable.original_text}<<<END_CANDIDATE>>>{suffix}"

    async def verify_field_candidates(
        self,
        document: str,
        variables: list[Variable],
        mode: IdentificationMode,
    ) -> list[Variable]:
        """Mandatory semantic filter when field verification is enabled.

        The verifier may keep/drop/rename a grounded candidate, but it can never
        change originalText or position. Failure is fail-closed: an incomplete
        semantic decision must never be committed to Word as a field.
        """
        if not self.settings.ollama_enable_field_verifier or not variables:
            return variables

        kept: list[Variable] = []
        batch_size = 24
        for batch_start in range(0, len(variables), batch_size):
            batch = variables[batch_start : batch_start + batch_size]
            candidate_rows = []
            for index, variable in enumerate(batch):
                candidate_rows.append(
                    {
                        "index": index,
                        "currentLabel": variable.name,
                        "originalText": variable.original_text,
                        "context": self._verification_context(document, variable),
                    }
                )

            user = (
                f"Document mode: {mode.value}. Classify every candidate below. "
                "Candidates are already text-grounded; do not propose replacement spans.\n"
                + json.dumps({"candidates": candidate_rows}, ensure_ascii=False)
            )
            try:
                raw = await self._call(
                    user,
                    FIELD_VERIFY_SYSTEM,
                    FIELD_VERIFY_SCHEMA,
                    model=self.settings.ollama_verifier_model,
                )
                decisions_raw = raw.get("decisions", [])
                decisions: dict[int, dict[str, Any]] = {}
                if isinstance(decisions_raw, list):
                    for decision in decisions_raw:
                        if not isinstance(decision, dict):
                            continue
                        try:
                            idx = int(decision.get("index"))
                        except (TypeError, ValueError):
                            continue
                        if 0 <= idx < len(batch) and idx not in decisions:
                            decisions[idx] = decision

                for index, variable in enumerate(batch):
                    decision = decisions.get(index)
                    if not decision:
                        raise AIOutputInvalid(
                            f"Field verifier omitted decision for candidate index {index}."
                        )
                    classification = str(decision.get("classification") or "ambiguous").lower()
                    if classification in {"static_text", "heading", "label"}:
                        log.debug(
                            "Verifier rejected %r as %s",
                            variable.original_text[:100],
                            classification,
                        )
                        continue

                    suggested = str(decision.get("suggestedLabel") or "").strip()
                    if suggested and len(suggested) <= 100:
                        variable.name = suggested
                    variable.decision_source = "qwen"
                    variable.classification = "ambiguous" if classification == "ambiguous" else "replaceable_value"
                    variable.reason_codes = list(dict.fromkeys([*variable.reason_codes, f"qwen_{classification}"]))
                    if classification == "ambiguous":
                        variable.review_state = "needs_review"
                        variable.confidence_score = min(variable.confidence_score or 0.6, 0.6)
                    else:
                        variable.review_state = "accepted"
                    kept.append(variable)
            except Exception as exc:
                log.error(
                    "Field verifier failed for batch %s-%s: %s",
                    batch_start,
                    batch_start + len(batch) - 1,
                    exc,
                )
                raise

        return finalize(kept, document)

    async def process_chunk(
        self,
        chunk: str,
        offset: int,
        document: str,
        known: list[Variable],
        mode: IdentificationMode,
        det: list[Variable],
    ) -> list[Variable]:
        anchors = self._scope(chunk, offset, det)
        system = prompt_for_mode(mode)
        raw = await self._call(
            self._user_prompt(chunk, anchors, self._scope_known(chunk, known), mode),
            system,
            model=self.settings.field_model,
        )
        llm = self._anchor_llm_vars(raw, chunk, offset)

        passes = (
            max(2, self.settings.ollama_extraction_passes)
            if mode == IdentificationMode.LEGAL
            else max(1, self.settings.ollama_extraction_passes)
        )
        for _ in range(1, passes):
            # Reliability rule: when a configured semantic pass fails, abort the
            # logical detection job instead of committing a partially evaluated
            # field set to Word.
            recovery = await self._call(
                self._recovery_prompt(chunk, anchors + llm, mode),
                system,
                model=self.settings.field_model,
            )
            llm.extend(self._anchor_llm_vars(recovery, chunk, offset))

        candidates = finalize(anchors + llm, document)
        # Streaming clients wrap chunk results progressively, so semantic
        # verification must happen before the chunk is emitted when enabled.
        return await self.verify_field_candidates(document, candidates, mode)

    async def preview_candidates(
        self,
        document: str,
        boilerplate_values: set[str] | None = None,
        *,
        allow_external_system1: bool = False,
    ) -> tuple[list[Variable], IdentificationMode]:
        """Return deterministic/System-1 candidates for review without Qwen.

        Used only as a fail-closed preview when System-2 AI is unavailable. Every
        returned candidate is forced to needs_review so callers can display useful
        evidence without ever auto-binding it into Word.
        """
        mode = classify_document(document)
        candidates = await self._deterministic(document, mode, boilerplate_values, allow_external_system1=allow_external_system1)
        for variable in candidates:
            variable.review_state = "needs_review"
            variable.reason_codes = list(dict.fromkeys([*variable.reason_codes, "system2_unavailable_preview"]))
        return candidates, mode

    def _large_document_warnings(
        self,
        document: str,
        chunks: list[tuple[str, int]],
        *,
        total_candidates: int | None = None,
        shown_candidates: int | None = None,
    ) -> list[str]:
        warnings = [
            (
                "This document is large, so AutoDraft used the grounded deterministic "
                "detector for this Auto Detect run instead of waiting for a full local "
                f"System-2 pass across {len(chunks)} chunks. Candidates are shown for "
                "review only and the Word document is not modified automatically."
            )
        ]
        if (
            total_candidates is not None
            and shown_candidates is not None
            and total_candidates > shown_candidates
        ):
            warnings.append(
                f"AutoDraft found {total_candidates} grounded review candidates and "
                f"showed the first {shown_candidates} condensed candidates so the Word "
                "task pane stays responsive."
            )
        return warnings

    def _large_document_review_candidates(self, variables: list[Variable]) -> list[Variable]:
        """Expose deterministic large-document candidates without auto-binding them.

        Large legal bundles often repeat the same values across complaint,
        affidavit, notice and index pages. Keeping every repeated review-only
        occurrence overwhelms the Word webview without giving the lawyer a better
        first pass, so collapse repeated semantic/value pairs and cap the preview.
        """
        review_only: list[Variable] = []
        seen: set[tuple[str, str]] = set()
        limit = max(1, int(self.settings.ollama_large_document_review_candidate_limit))
        for variable in variables:
            key = (semantic_family(variable.name), normalize(variable.original_text))
            if key in seen:
                continue
            seen.add(key)
            reason_codes = list(
                dict.fromkeys([*variable.reason_codes, "large_document_review_only"])
            )
            review_only.append(
                variable.model_copy(
                    update={
                        "review_state": "needs_review",
                        "reason_codes": reason_codes,
                    }
                )
            )
            if len(review_only) >= limit:
                break
        return review_only

    async def identify_variables(
        self,
        document: str,
        known: list[Variable] | None = None,
        boilerplate_values: set[str] | None = None,
        *,
        allow_external_system1: bool = False,
    ) -> tuple[list[Variable], bool, IdentificationMode, list[str]]:
        known = known or []
        mode = classify_document(document)
        det = await self._deterministic(document, mode, boilerplate_values, allow_external_system1=allow_external_system1)
        chunks = self.chunks(document)
        if len(document) > self.settings.ollama_semantic_document_char_limit:
            review_only = self._large_document_review_candidates(det)
            return (
                review_only,
                False,
                mode,
                self._large_document_warnings(
                    document,
                    chunks,
                    total_candidates=len(det),
                    shown_candidates=len(review_only),
                )
                + coverage_warnings(document, review_only, mode),
            )
        tasks = [
            asyncio.create_task(self.process_chunk(chunk, offset, document, known, mode, det))
            for chunk, offset in chunks
        ]
        found: list[Variable] = []
        failures = 0
        try:
            for task in asyncio.as_completed(tasks):
                try:
                    found.extend(await task)
                except Exception as exc:
                    failures += 1
                    log.warning("Chunk extraction failed: %s", exc)

            if failures:
                raise AIProviderUnavailable(
                    f"Field detection could not be completed because {failures} extraction chunk(s) failed."
                )
            final = finalize(det + found, document)
            final = await self.verify_field_candidates(document, final, mode)
            return (
                final,
                False,
                mode,
                coverage_warnings(document, final, mode),
            )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def stream_variables(
        self,
        document: str,
        known: list[Variable] | None = None,
        boilerplate_values: set[str] | None = None,
        *,
        allow_external_system1: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        known = known or []
        mode = classify_document(document)
        chunks = self.chunks(document)
        det = await self._deterministic(document, mode, boilerplate_values, allow_external_system1=allow_external_system1)
        yield {
            "event": "start",
            "data": {
                "identificationMode": mode.value,
                "totalChunks": len(chunks),
                "plan": len(chunks),
                "blocks": len(chunks),
            },
        }
        if len(document) > self.settings.ollama_semantic_document_char_limit:
            review_only = self._large_document_review_candidates(det)
            warnings = self._large_document_warnings(
                document,
                chunks,
                total_candidates=len(det),
                shown_candidates=len(review_only),
            ) + coverage_warnings(document, review_only, mode)
            yield {
                "event": "chunk_done",
                "data": {
                    "chunkIndex": 0,
                    "totalChunks": 1,
                    "variables": [
                        v.model_dump(by_alias=True, exclude_none=True) for v in review_only
                    ],
                },
            }
            yield {
                "event": "progress",
                "data": {"completed": 1, "total": 1, "percentage": 100.0},
            }
            yield {
                "event": "_final",
                "data": {
                    "variables": review_only,
                    "ai_failed": False,
                    "identificationMode": mode.value,
                    "coverageWarnings": warnings,
                    "plan": len(chunks),
                    "blocks": len(chunks),
                },
            }
            return

        async def run(i: int, chunk: str, offset: int):
            try:
                return i, await self.process_chunk(chunk, offset, document, known, mode, det), None
            except Exception as exc:
                return i, [], str(exc)

        tasks = [
            asyncio.create_task(run(i, chunk, offset))
            for i, (chunk, offset) in enumerate(chunks)
        ]
        collected: list[Variable] = []
        completed = 0
        failures = 0
        try:
            for fut in asyncio.as_completed(tasks):
                i, vars_, err = await fut
                completed += 1
                if err:
                    failures += 1
                    yield {"event": "error", "data": {"chunkIndex": i, "message": err}}
                else:
                    collected.extend(vars_)
                    yield {
                        "event": "chunk_done",
                        "data": {
                            "chunkIndex": i,
                            "totalChunks": len(chunks),
                            "variables": [
                                v.model_dump(by_alias=True, exclude_none=True) for v in vars_
                            ],
                        },
                    }
                yield {
                    "event": "progress",
                    "data": {
                        "completed": completed,
                        "total": len(chunks),
                        "percentage": round(completed / max(1, len(chunks)) * 100, 1),
                    },
                }

            if failures:
                yield {
                    "event": "_final",
                    "data": {
                        "variables": [],
                        "ai_failed": True,
                        "identificationMode": mode.value,
                        "coverageWarnings": [
                            f"Detection aborted because {failures} extraction chunk(s) failed."
                        ],
                        "plan": len(chunks),
                        "blocks": len(chunks),
                    },
                }
                return
            final = finalize(det + collected, document)
            final = await self.verify_field_candidates(document, final, mode)
            yield {
                "event": "_final",
                "data": {
                    "variables": final,
                    "ai_failed": False,
                    "identificationMode": mode.value,
                    "coverageWarnings": coverage_warnings(document, final, mode),
                    "plan": len(chunks),
                    "blocks": len(chunks),
                },
            }
        finally:
            # Important for Word/WebView disconnects: cancelling the HTTP/job
            # consumer must not leave orphaned per-chunk model calls running.
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def structured_analysis(
        self,
        system: str,
        user: str,
        *,
        schema: dict[str, Any] | str = "json",
        purpose: str = "general",
    ) -> dict[str, Any]:
        model = self.settings.ollama_model
        if purpose == "field":
            model = self.settings.field_model
        elif purpose == "drafting":
            model = self.settings.drafting_model
        elif purpose == "review":
            model = self.settings.review_model
        return await self._call(user, system, schema, model=model)
