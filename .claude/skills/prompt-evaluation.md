---
name: prompt-evaluation
description: Use when iterating on a prompt and you need objective signal — comparing prompt versions, regression-testing prompt changes, measuring instruction-following on structured outputs (JSON/code/regex), or scoring outputs across a dataset instead of eyeballing single responses
---

# Prompt Evaluation

## Overview

Prompt engineering is how you write a prompt; **prompt evaluation is how you measure whether it works**. The eval loop turns prompt iteration from "this looks better" into a numeric score you can compare across versions.

The pipeline:

1. Draft a prompt template with an input slot.
2. Build a dataset of inputs that resemble production traffic.
3. Run each input through the prompt → Claude → output.
4. Grade each output (deterministic checks, a model grader, or both).
5. Average the scores. Change the prompt. Re-run. Compare.

## When to Use

- Comparing two versions of the same prompt ("does the new system prompt actually help?")
- Catching regressions before shipping a prompt change
- Measuring instruction-following on structured outputs (JSON, code, regex)
- Tuning temperature, model, or prefill strategies with evidence

**Don't bother when:**
- One-shot prompts you'll read once and never run again
- The "correct" output has no quality criteria you can articulate

## The Five Steps

| Step | Output | Notes |
|------|--------|-------|
| 1. Draft prompt | Template with input slot | Start minimal; you'll improve it across iterations |
| 2. Build dataset | List of `{ task: ... }` JSON objects | 10–50 entries; generate with Claude or write by hand |
| 3. Run prompt | One Claude response per dataset row | Parallelize with `Promise.all` |
| 4. Grade | Numeric score per row | Code grader, model grader, or both |
| 5. Iterate | New prompt version + new average | Track scores per version |

## Project Notes

This project's frontend is React/TypeScript for modern supported Office webviews. TypeScript currently transpiles to ES5 for broad syntax compatibility, but IE 11 is not a supported runtime. Prompt-eval scripts should run as **Node scripts** (e.g. `word-extension/scripts/eval-*.ts` executed with `ts-node` or `tsx`), **not** as part of the bundled add-in. They need network access to Anthropic and a real filesystem; the bundle doesn't.

Install the SDK in the workspace where the eval script lives:

```bash
npm install @anthropic-ai/sdk
```

## Quick Reference

### Helpers

```typescript
import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic(); // reads ANTHROPIC_API_KEY
const MODEL = "claude-haiku-4-5";

type Role = "user" | "assistant";
type Message = { role: Role; content: string };

function addUserMessage(messages: Message[], text: string): void {
  messages.push({ role: "user", content: text });
}

function addAssistantMessage(messages: Message[], text: string): void {
  messages.push({ role: "assistant", content: text });
}

async function chat(
  messages: Message[],
  opts: { system?: string; temperature?: number; stopSequences?: string[] } = {}
): Promise<string> {
  const response = await client.messages.create({
    model: MODEL,
    max_tokens: 1000,
    messages,
    temperature: opts.temperature ?? 1.0,
    ...(opts.system ? { system: opts.system } : {}),
    ...(opts.stopSequences ? { stop_sequences: opts.stopSequences } : {}),
  });
  const block = response.content[0];
  if (block.type !== "text") throw new Error(`Expected text block, got ${block.type}`);
  return block.text;
}
```

### Generate a dataset with Claude

Uses prefill + stop sequences for clean JSON (see the `response-streaming` skill for that pattern):

```typescript
import { writeFileSync } from "node:fs";

type TestCase = { task: string };

async function generateDataset(): Promise<TestCase[]> {
  const prompt = `
Generate an evaluation dataset for prompts that produce Python, JSON, or regex for AWS tasks.
Return an array of JSON objects, each with a "task" field describing what to generate.

Example:
\`\`\`json
[
  {"task": "Description of task"}
]
\`\`\`

Generate 10 objects, each solvable by a single function / object / regex.
`;
  const messages: Message[] = [];
  addUserMessage(messages, prompt);
  addAssistantMessage(messages, "```json");
  const text = await chat(messages, { stopSequences: ["```"] });
  return JSON.parse(text);
}

const dataset = await generateDataset();
writeFileSync("dataset.json", JSON.stringify(dataset, null, 2));
```

### The eval loop

```typescript
type GradedResult = {
  testCase: TestCase;
  output: string;
  score: number;
  reasoning: string;
};

async function runPrompt(testCase: TestCase): Promise<string> {
  const prompt = `
Please solve the following task:

${testCase.task}
`;
  const messages: Message[] = [];
  addUserMessage(messages, prompt);
  return chat(messages);
}

async function runTestCase(testCase: TestCase): Promise<GradedResult> {
  const output = await runPrompt(testCase);
  const grade = await gradeByModel(testCase, output);
  return { testCase, output, score: grade.score, reasoning: grade.reasoning };
}

async function runEval(dataset: TestCase[]): Promise<GradedResult[]> {
  // Parallel — Anthropic SDK handles concurrency. Cap with a small pool if dataset is large.
  const results = await Promise.all(dataset.map(runTestCase));
  const avg = results.reduce((s, r) => s + r.score, 0) / results.length;
  console.log(`Average score: ${avg.toFixed(2)}`);
  return results;
}
```

## Graders

### Code grader (deterministic) — prefer when you can

When success has a precise definition, **always prefer code**. Cheap, fast, no LLM noise.

```typescript
function gradeFormat(output: string): number {
  const t = output.trim();
  return t.startsWith("```") || t.startsWith("{") || t.startsWith("[") ? 10 : 0;
}

function gradeValidJson(output: string): number {
  try {
    JSON.parse(output);
    return 10;
  } catch {
    return 0;
  }
}
```

Other things code can grade for free: matches a regex, parses (`new RegExp(output)` for regex outputs, `ts.createSourceFile` for TS, `acorn.parse` for JS), runs without exception, length within bounds, contains required keys.

### Model grader — for subjective dimensions

For things code can't judge (helpfulness, completeness, tone), feed the output to another Claude call and ask for a score with reasoning:

```typescript
type ModelGrade = {
  strengths: string[];
  weaknesses: string[];
  reasoning: string;
  score: number;
};

async function gradeByModel(testCase: TestCase, output: string): Promise<ModelGrade> {
  const evalPrompt = `
You are an expert code reviewer. Evaluate this AI-generated solution.

Task: ${testCase.task}
Solution: ${output}

Return a JSON object:
- "strengths": array of 1-3 strengths
- "weaknesses": array of 1-3 weaknesses
- "reasoning": one paragraph explaining the assessment
- "score": integer 1-10
`;
  const messages: Message[] = [];
  addUserMessage(messages, evalPrompt);
  addAssistantMessage(messages, "```json");
  const text = await chat(messages, { stopSequences: ["```"], temperature: 0 });
  return JSON.parse(text);
}
```

**Why force strengths/weaknesses/reasoning before the score?** Without that scaffolding, model graders cluster around 6/10 for everything. Articulating evidence first moves scores meaningfully and gives you something to read when results are surprising.

### Combining graders

Track each dimension separately. Don't average a deterministic format check with a subjective quality score — you'll lose signal:

```typescript
return {
  formatOk: gradeFormat(output),                     // 0 or 10
  validJson: gradeValidJson(output),                 // 0 or 10
  quality: (await gradeByModel(testCase, output)).score, // 1-10
};
```

## Iteration Loop

Once the pipeline runs, the work is rerunning it with prompt changes:

1. Save dataset and per-version results to disk (`dataset.json`, `results-v1.json`, `results-v2.json`).
2. After each prompt change, re-run `runEval` and **diff scores per row** — the overall average can hide regressions on specific cases.
3. When the average plateaus, look at the lowest-scoring rows. Their failure mode is what your next prompt edit should target.

## Common Mistakes

- **Tiny dataset.** 3 cases gives noisy averages. Aim for 10–50 spanning the variation you expect in production.
- **Dataset that all looks the same.** If every row is "write a JSON config," you're testing one narrow capability. Mix task shapes deliberately.
- **No baseline run before iterating.** You can't tell if a change helped without v1's score recorded.
- **Model-grading what code could check.** "Is this valid JSON" is a `JSON.parse` call, not a $0.001 LLM call. Use the model only when code can't judge.
- **Trusting a single score.** Model graders are noisy. Run important comparisons 2–3 times, or use `temperature: 0` for the grader (as shown above).
- **Grading without showing the task.** If the grader sees only the output, it can't judge instruction-following. Always pass the original task into the grader prompt.
- **Unbounded `Promise.all` on huge datasets.** 500 rows fired in parallel will hit rate limits. For large evals, use a concurrency pool (e.g. `p-limit`) or batch.
- **Bundling eval scripts into the Word add-in.** This is a Node-only workflow — never import `@anthropic-ai/sdk` from `word-extension/src/`. The API key would leak to the client and the bundle would balloon.
- **Stuffing huge outputs into the grader prompt.** Truncate or summarize; otherwise the grader's score becomes about the truncation, not the answer.
- **Different models for grading and generation by default.** Often fine, but a weaker grader can mark a stronger generator's output down for things it doesn't understand. Use the same tier or stronger for the grader.

## Saving Results

Persist enough to debug a regression a week later:

```typescript
import { writeFileSync } from "node:fs";

const record = {
  promptVersion: "v3",
  model: MODEL,
  datasetPath: "dataset.json",
  averageScore: 7.4,
  results, // GradedResult[]
};
writeFileSync("results-v3.json", JSON.stringify(record, null, 2));
```

When v4 scores worse, diff per-row against v3 to find which cases regressed and why.
