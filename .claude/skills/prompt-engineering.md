---
name: prompt-engineering
description: Use when refining a prompt that produces vague, off-format, or unreliable output — covers iterative improvement (clarity, specificity, XML structure, examples) for LLM prompts. Apply when output drifts in length/format, ignores constraints, mishandles edge cases like sarcasm, or hallucinates structure. Pair with prompt-evaluation to measure each change.
---

# Prompt Engineering

## Overview

Prompt engineering is taking a prompt and **systematically improving it** so the model produces more reliable, higher-quality output. It is iterative: draft → evaluate → apply a technique → re-evaluate. Each technique below is a tool for one specific failure mode — apply the one that matches what your current prompt is getting wrong, not all of them at once.

**Companion skill:** Use `prompt-evaluation` to score versions before/after each change. Without measurement, "improvement" is vibes.

## The Loop

1. **Set a goal.** What does the output need to contain or do?
2. **Write a naive baseline.** A short, ugly first draft. Don't pre-optimize.
3. **Evaluate.** Run a small dataset (~3–10 cases) through it. Note what fails.
4. **Apply ONE technique** below targeting the specific failure.
5. **Re-evaluate.** Compare scores. Keep the change if it helped; revert if not.

Change one thing at a time. If you change three things and the score goes up, you don't know which one helped.

## Technique 1 — Be Clear and Direct

**Use when:** the prompt asks a vague question or describes the task indirectly.

| Symptom | Fix |
|---|---|
| Output rambles or goes off-topic | Lead with an imperative verb (Write, Generate, List, Identify) |
| Model asks clarifying questions back | State the deliverable explicitly, not as a question |
| Output length varies wildly | Specify length and format up front |

**Before:** `What should this person eat?`
**After:** `Generate a one-day meal plan for an athlete that meets their dietary restrictions.`

Treat the model as a capable assistant who needs direction, not someone who has to guess intent.

## Technique 2 — Add Specificity

**Use when:** the output is on-topic but missing required elements, or formatted inconsistently across runs.

Two complementary patterns:

### 2a. Output quality guidelines

List the qualities the output must have. Use this in **almost every prompt**.

```
Guidelines:
1. Include daily calorie total
2. Show protein/fat/carb amounts in grams
3. Specify when to eat each meal
4. Use only foods that fit restrictions
5. List portion sizes in grams
```

### 2b. Process steps

Tell the model HOW to think. Use for complex reasoning, decisions, multi-perspective tasks.

```
Steps:
1. Brainstorm 3 candidate approaches
2. Evaluate each against the constraints
3. Pick the best one
4. Output the final plan
```

**Rule of thumb:** always include 2a; add 2b when the task involves judgment or planning.

## Technique 3 — Provide Structure with XML Tags

**Use when:** the prompt mixes instructions with data (code, documents, user input, examples), or is long enough that the model confuses sections.

Wrap distinct content in descriptive, named tags:

```
<athlete_information>
- Height: 6'2"
- Weight: 180 lbs
- Goal: Build muscle
- Dietary restrictions: Vegetarian
</athlete_information>

Generate a meal plan based on the athlete information above.
```

**Tag-naming rules:**
- Specific over generic: `<sales_records>` beats `<data>`, `<my_code>` beats `<input>`
- Match closing tag exactly
- Tags are not standardized — pick names that describe the content

**When mandatory:** the prompt interpolates user-supplied data. Without delimiters, prompt-injection-shaped content can blur into instructions.

## Technique 4 — Provide Examples (Few-Shot)

**Use when:** instructions alone can't capture the pattern — sarcasm, tone, exact JSON shape, edge cases, ambiguous classification.

**One-shot:** one example to anchor the pattern.
**Multi-shot:** multiple examples covering different scenarios. Use when you need to handle edge cases or multiple valid output shapes.

Always wrap examples in tags so the model knows where the demonstration ends:

```
<example>
  <sample_input>Oh great, another flight delay. Excellent.</sample_input>
  <ideal_output>Negative</ideal_output>
  <reasoning>Sarcasm — surface words are positive, sentiment is negative.</reasoning>
</example>
```

**Sourcing examples:** pull your highest-scoring outputs from `prompt-evaluation` runs. Top-scored real outputs > hand-written examples.

**Annotate why** an example is ideal — a one-line `<reasoning>` block stops the model from copying surface features instead of the underlying pattern.

## Quick Reference: Symptom → Technique

| Failing behavior | Reach for |
|---|---|
| Output is generic / off-topic | Technique 1 (clear & direct) |
| Output missing required fields | Technique 2a (quality guidelines) |
| Reasoning shallow on complex task | Technique 2b (process steps) |
| Model conflates instructions with data | Technique 3 (XML tags) |
| Edge cases handled wrong (sarcasm, weird formats) | Technique 4 (examples) |
| Output format inconsistent run-to-run | Technique 2a + Technique 4 |

## Common Mistakes

- **Stacking techniques without measuring.** Adding XML + examples + 5 guidelines simultaneously hides which change helped. One change per iteration.
- **Examples that drift from the real distribution.** Toy examples teach toy behavior. Use realistic inputs.
- **Process steps for trivial tasks.** Adding "think step by step" to a one-line lookup just bloats the prompt.
- **Generic XML tag names.** `<input>`/`<data>`/`<text>` give the model no semantic signal — use content-descriptive names.
- **Forgetting to re-evaluate.** A change that "feels" better is not the same as a change that scores better. Run the eval.

## Order of Operations

When a prompt has many problems, fix in this order — each step makes the next easier to evaluate:

1. Clarity & direct verb (Technique 1) — fixes the most cases for the least effort
2. Output guidelines (Technique 2a) — locks down format
3. XML structure (Technique 3) — once you start interpolating variables
4. Process steps (Technique 2b) — when reasoning is still shallow
5. Examples (Technique 4) — for the edge cases left after 1–4
