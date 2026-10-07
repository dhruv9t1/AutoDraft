/**
 * Variable-identification prompt evaluation harness.
 *
 * Runs each fixture in eval-fixtures/variables/*.json against the running
 * backend's /api/documents/identify-variables endpoint, then applies four
 * deterministic code graders + one optional model grader to score the output.
 * Results are written to eval-results/results-<version>.json so versions can
 * be diffed per-row to find regressions.
 *
 * Usage:
 *   # Backend must be running at $EVAL_BACKEND_URL (default http://localhost:3001)
 *   # Ollama must be running at $OLLAMA_API_URL (default http://localhost:11434)
 *   npx tsx scripts/eval-variable-identification.ts v2
 *
 * The detector under evaluation is always the running backend endpoint, so it
 * uses the backend's configured FIELD_MODEL/OLLAMA_MODEL. Override only the
 * optional naming-grader model with EVAL_GRADER_MODEL (default qwen3:4b):
 *   EVAL_GRADER_MODEL=qwen3:4b npx tsx scripts/eval-variable-identification.ts v2
 *
 * Skip the model grader (faster, code graders only):
 *   EVAL_SKIP_MODEL_GRADER=1 npx tsx scripts/eval-variable-identification.ts v2
 *
 * Fixture format (eval-fixtures/variables/<name>.json):
 *   {
 *     "name": "human-readable label",
 *     "document": "<full plaintext doc...>",
 *     "expected": [
 *       { "name": "Reference Number", "originalText": "411/2026" },
 *       ...
 *     ]
 *   }
 *
 * NB: this file is a Node-only script. It must NEVER be imported from
 * word-extension/src.
 */

import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// ─────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────

interface ExpectedVariable {
  name: string;
  originalText: string;
}

interface Fixture {
  name: string;
  document: string;
  expected: ExpectedVariable[];
}

interface ReturnedVariable {
  name: string;
  originalText: string;
  position: number;
  confidenceScore?: number;
}

interface IdentifyResponse {
  variables: ReturnedVariable[];
  identificationPercentage: number;
  status: string;
  message?: string;
}

interface CodeScores {
  verbatim: number;        // 0–10  fraction of returned vars whose originalText is in the doc
  noOverlap: number;       // 0 or 10  no returned originalText is a substring of another
  noListMarkers: number;   // 0 or 10  no returned originalText is a layout marker
  noDuplicates: number;    // 0 or 10  no two returned vars share the same originalText
  recall: number;          // 0–10  fraction of expected vars actually returned
}

interface NamingGrade {
  score: number;           // 1–10  subjective naming quality
  reasoning: string;
  strengths: string[];
  weaknesses: string[];
}

interface RowResult {
  fixture: string;
  returned: ReturnedVariable[];
  code: CodeScores;
  naming?: NamingGrade;
  errors: string[];
}

// ─────────────────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────────────────

const VERSION = process.argv[2] || `run-${Date.now()}`;
const BACKEND_URL = process.env.EVAL_BACKEND_URL || "http://localhost:3001";
const SKIP_MODEL_GRADER = process.env.EVAL_SKIP_MODEL_GRADER === "1";
const OLLAMA_URL = process.env.OLLAMA_API_URL || "http://localhost:11434";
const GRADER_MODEL = process.env.EVAL_GRADER_MODEL || "qwen3:4b";
const OLLAMA_API_KEY = process.env.OLLAMA_API_KEY || "";
const FIXTURE_DIR = join(__dirname, "eval-fixtures", "variables");
const RESULTS_DIR = join(__dirname, "eval-results");

// ─────────────────────────────────────────────────────────────────────────
// Code graders (cheap, deterministic — prefer when possible per the skill)
// ─────────────────────────────────────────────────────────────────────────

const LIST_MARKER_RX = /^\s*[\[(]?\d{1,3}[\])]?\.?\s*$|^…?\.*\d+\.?$|^::?\s*\d+\s*::?$/;

function gradeVerbatim(returned: ReturnedVariable[], doc: string): number {
  if (returned.length === 0) return 10; // vacuously true
  const present = returned.filter((v) => doc.includes(v.originalText)).length;
  return (present / returned.length) * 10;
}

function gradeNoOverlap(returned: ReturnedVariable[]): number {
  for (let i = 0; i < returned.length; i++) {
    for (let j = 0; j < returned.length; j++) {
      if (i === j) continue;
      const a = returned[i].originalText;
      const b = returned[j].originalText;
      if (a !== b && a.length > 0 && b.length > 0 && b.includes(a)) {
        return 0; // a is a strict substring of b
      }
    }
  }
  return 10;
}

function gradeNoListMarkers(returned: ReturnedVariable[]): number {
  return returned.some((v) => LIST_MARKER_RX.test(v.originalText.trim())) ? 0 : 10;
}

function gradeNoDuplicates(returned: ReturnedVariable[]): number {
  const seen = new Set<string>();
  for (const v of returned) {
    const k = v.originalText.trim().toLowerCase();
    if (!k) continue;
    if (seen.has(k)) return 0;
    seen.add(k);
  }
  return 10;
}

function gradeRecall(returned: ReturnedVariable[], expected: ExpectedVariable[]): number {
  if (expected.length === 0) return 10;
  const returnedSet = new Set(returned.map((v) => v.originalText.trim().toLowerCase()));
  const hits = expected.filter((e) => returnedSet.has(e.originalText.trim().toLowerCase())).length;
  return (hits / expected.length) * 10;
}

// ─────────────────────────────────────────────────────────────────────────
// Model grader (optional — only for naming quality, which code can't judge)
// Per the skill: force strengths/weaknesses/reasoning BEFORE the score so the
// grader doesn't cluster around 6/10.
// ─────────────────────────────────────────────────────────────────────────

async function gradeNaming(
  fixture: Fixture,
  returned: ReturnedVariable[]
): Promise<NamingGrade> {
  const evalPrompt = `You are a senior legal-document analyst. Grade the variable NAMES (not the originalText values) chosen for the fixture below. Naming quality means: standard legal terminology ("Complainant"/"Accused" not "Sender"/"Receiver"), specific over generic ("Cheque Bank IFSC" not "Bank Code"), consistent across related fields.

<fixture_name>${fixture.name}</fixture_name>

<returned_variables>
${returned.map((v) => `- name="${v.name}"  originalText="${v.originalText.slice(0, 80)}${v.originalText.length > 80 ? "…" : ""}"`).join("\n")}
</returned_variables>

Return a JSON object with exactly these fields, in this order:
- "strengths": array of 1-3 short strings describing strong naming choices
- "weaknesses": array of 1-3 short strings describing weak/generic/inconsistent names
- "reasoning": one paragraph (3-5 sentences) explaining the overall assessment
- "score": integer 1-10

Respond with the JSON object only — no prose, no code fences.`;

  const headers: Record<string, string> = { "content-type": "application/json" };
  if (OLLAMA_API_KEY) headers.authorization = `Bearer ${OLLAMA_API_KEY}`;

  const res = await fetch(`${OLLAMA_URL}/api/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      model: GRADER_MODEL,
      stream: false,
      format: "json",
      options: { temperature: 0 },
      messages: [{ role: "user", content: evalPrompt }],
    }),
  });

  if (!res.ok) {
    throw new Error(`Ollama returned ${res.status} ${res.statusText}: ${await res.text()}`);
  }

  const body = (await res.json()) as { message?: { content?: string }; response?: string };
  const content = body.message?.content ?? body.response ?? "";
  if (!content) throw new Error(`Empty response from Ollama: ${JSON.stringify(body)}`);
  return JSON.parse(content) as NamingGrade;
}

// ─────────────────────────────────────────────────────────────────────────
// Backend caller
// ─────────────────────────────────────────────────────────────────────────

async function callBackend(documentContent: string): Promise<IdentifyResponse> {
  const url = `${BACKEND_URL}/api/documents/identify-variables`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ documentContent }),
  });
  if (!res.ok) {
    throw new Error(`Backend returned ${res.status} ${res.statusText}: ${await res.text()}`);
  }
  return (await res.json()) as IdentifyResponse;
}

// ─────────────────────────────────────────────────────────────────────────
// Per-row runner
// ─────────────────────────────────────────────────────────────────────────

async function runFixture(fixture: Fixture): Promise<RowResult> {
  const errors: string[] = [];
  let returned: ReturnedVariable[] = [];

  try {
    const resp = await callBackend(fixture.document);
    returned = resp.variables;
  } catch (e) {
    errors.push(`backend call failed: ${e instanceof Error ? e.message : String(e)}`);
  }

  const code: CodeScores = {
    verbatim: gradeVerbatim(returned, fixture.document),
    noOverlap: gradeNoOverlap(returned),
    noListMarkers: gradeNoListMarkers(returned),
    noDuplicates: gradeNoDuplicates(returned),
    recall: gradeRecall(returned, fixture.expected),
  };

  let naming: NamingGrade | undefined;
  if (!SKIP_MODEL_GRADER && returned.length > 0) {
    try {
      naming = await gradeNaming(fixture, returned);
    } catch (e) {
      errors.push(`naming grader failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  return { fixture: fixture.name, returned, code, naming, errors };
}

// ─────────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────────

function avg(nums: number[]): number {
  return nums.length === 0 ? 0 : nums.reduce((a, b) => a + b, 0) / nums.length;
}

async function main(): Promise<void> {
  // Load fixtures
  const fixtureFiles = readdirSync(FIXTURE_DIR).filter((f) => f.endsWith(".json"));
  if (fixtureFiles.length === 0) {
    console.error(`No fixtures found in ${FIXTURE_DIR}. See README for the expected format.`);
    process.exit(1);
  }
  const fixtures: Fixture[] = fixtureFiles.map((f) => {
    const raw = readFileSync(join(FIXTURE_DIR, f), "utf8");
    return JSON.parse(raw) as Fixture;
  });

  console.log(
    `Running ${fixtures.length} fixture(s) against ${BACKEND_URL} for prompt version "${VERSION}"…`
  );
  if (SKIP_MODEL_GRADER) console.log("  (model grader disabled — code graders only)");

  // Run rows in parallel — Ollama and the backend handle concurrency.
  // For >50 fixtures, consider a concurrency pool (p-limit) to avoid hammering
  // either side; for typical 10–20 fixture datasets this is fine.
  const results: RowResult[] = await Promise.all(fixtures.map(runFixture));

  // Aggregate per-dimension averages — keep them separate per the skill so a
  // perfect "no list markers" score doesn't mask a recall regression.
  const summary = {
    verbatim: avg(results.map((r) => r.code.verbatim)),
    noOverlap: avg(results.map((r) => r.code.noOverlap)),
    noListMarkers: avg(results.map((r) => r.code.noListMarkers)),
    noDuplicates: avg(results.map((r) => r.code.noDuplicates)),
    recall: avg(results.map((r) => r.code.recall)),
    naming: SKIP_MODEL_GRADER
      ? null
      : avg(results.map((r) => r.naming?.score ?? 0).filter((s) => s > 0)),
  };

  console.log("\n── Summary ─────────────────────");
  for (const [k, v] of Object.entries(summary)) {
    if (v === null) {
      console.log(`  ${k.padEnd(15)}  (skipped)`);
    } else {
      console.log(`  ${k.padEnd(15)}  ${(v as number).toFixed(2)} / 10`);
    }
  }

  // Write results — keep enough to debug a regression a week later.
  const outPath = join(RESULTS_DIR, `results-${VERSION}.json`);
  writeFileSync(
    outPath,
    JSON.stringify(
      {
        promptVersion: VERSION,
        backendUrl: BACKEND_URL,
        timestamp: new Date().toISOString(),
        summary,
        results,
      },
      null,
      2
    )
  );
  console.log(`\nWrote ${outPath}`);
  console.log(
    `\nNext: re-run after editing build_system_prompt() in backend/src/ollama.rs (e.g. as v3) and diff per-row scores against this run.`
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
