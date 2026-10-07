---
name: response-streaming
description: Use when building chat UIs or any user-facing app on the Anthropic SDK where users wait 10+ seconds for Claude to finish, when handling MessageStart/ContentBlockDelta/MessageStop events, or when combining assistant prefilling with stop_sequences to constrain output to a single block (JSON, code, etc.)
---

# Response Streaming & Output Shaping for the Claude API

## Overview

Two related techniques for the Anthropic SDK that improve perceived latency and output precision:

1. **Streaming** — display Claude's response chunk-by-chunk as it generates, instead of blocking 10–30s for a full response.
2. **Prefilling + stop sequences** — seed the assistant turn with an opening token (e.g. ` ```json `) and stop generation when Claude tries to close it, yielding exactly the inner content with no preamble or trailing prose.

Both work on the same `client.messages.create` / `client.messages.stream` calls and compose cleanly.

## When to Use

**Stream when:**
- Building chat UIs, conversational agents, or any user-facing app
- Generating long-form output (essays, code, analysis) where total latency > 2s
- You want to forward tokens to a browser via SSE / WebSocket as they arrive

**Don't stream when:**
- Background jobs, batch pipelines, evals — you only need the final message
- Short structured outputs where the full call returns in < 1s
- Downstream code can't act on partial output anyway

**Use prefill + stop_sequences when:**
- You need pure JSON / XML / code with no "Sure, here's…" preamble
- You want to guarantee output stays inside one code fence
- You're parsing the response programmatically and any extra prose breaks it

## Stream Event Types

When `stream=True`, Claude emits a sequence of typed events:

| Event | Meaning | What you do with it |
|-------|---------|---------------------|
| `MessageStart` | Message is starting; contains initial `usage`, model, role | Initialize buffer |
| `ContentBlockStart` | New block (text, tool_use, etc.) starting | Note the block type/index |
| `ContentBlockDelta` | A chunk of generated text (or partial tool input JSON) | **Display this to the user** |
| `ContentBlockStop` | Current block finished | Finalize that block |
| `MessageDelta` | Top-level message updates (`stop_reason`, output `usage`) | Capture stop reason & token counts |
| `MessageStop` | Stream is done | Close connection, persist message |

The text the user sees lives in `ContentBlockDelta`. Everything else is metadata.

## Quick Reference

### Raw event loop

Use when you need every event type (e.g. forwarding tool-use deltas, logging usage):

```python
stream = client.messages.create(
    model=model,
    max_tokens=1000,
    messages=messages,
    stream=True,
)

for event in stream:
    print(event)
```

### Simplified text stream (recommended)

The SDK exposes a context manager that extracts just the text deltas — preferred for chat UIs:

```python
with client.messages.stream(
    model=model,
    max_tokens=1000,
    messages=messages,
) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)
```

The `with` block guarantees the underlying HTTP connection is closed even on exceptions.

### Streaming + final message for storage

You almost always want both: forward chunks to the client AND persist the assembled message (with `usage`, `stop_reason`, full content blocks) for history.

```python
with client.messages.stream(
    model=model,
    max_tokens=1000,
    messages=messages,
) as stream:
    for text in stream.text_stream:
        send_to_client(text)        # SSE / WebSocket / stdout

    final_message = stream.get_final_message()
    save_to_db(final_message)       # has full content, usage, stop_reason
```

Don't reconstruct the final message by concatenating `text` chunks yourself — you'd lose `usage`, `stop_reason`, and any non-text content blocks.

## Prefilling + Stop Sequences

The pattern: append a partial assistant message that opens a structure, then stop when Claude tries to close it.

```python
messages = []
add_user_message(messages, "Generate a very short EventBridge rule as JSON")
add_assistant_message(messages, "```json")

text = chat(messages, stop_sequences=["```"])
```

How it works:

1. **User turn** says what to generate.
2. **Prefilled assistant turn** ends with ` ```json `, so Claude's next token continues *inside* the fence — no "Here's the JSON:" preamble.
3. **`stop_sequences=["```"]`** ends generation the moment Claude emits the closing fence, so you don't pay for trailing prose or get partial extra output.

Result: `text` is the raw JSON body, ready to `json.loads()`.

### Variations

| Goal | Prefill | stop_sequences |
|------|---------|----------------|
| Pure JSON object | `{` | `}` (only if single object, no nesting) |
| Fenced JSON | `` ```json `` | `` ``` `` |
| XML tag content | `<answer>` | `</answer>` |
| Bullet list only | `- ` | `\n\n` |

**Caveat on `{`/`}`:** stop sequences are literal — a stop on `}` will fire on the first `}`, breaking nested objects. Prefer the fenced-code variant for non-trivial JSON.

### Combining with streaming

Prefill + stop_sequences works identically with `stream=True`. The prefilled tokens are NOT re-emitted in deltas — you only receive what Claude generates after the prefill, which is exactly the content you want to forward.

```python
with client.messages.stream(
    model=model,
    max_tokens=1000,
    messages=[
        {"role": "user", "content": "Generate a short EventBridge rule as JSON"},
        {"role": "assistant", "content": "```json"},
    ],
    stop_sequences=["```"],
) as stream:
    for text in stream.text_stream:
        forward_to_parser(text)

    final = stream.get_final_message()
    assert final.stop_reason == "stop_sequence"
```

## Common Mistakes

- **Hand-rolling event parsing when `text_stream` would do.** Use `client.messages.stream()` unless you specifically need tool-use deltas, usage events, or non-text blocks.
- **Concatenating chunks instead of `get_final_message()`.** You lose `usage`, `stop_reason`, and structured content. Always grab the final message for storage.
- **Forgetting the context manager.** Bare `stream=True` requires manual cleanup; a dropped connection on the client side can leak the upstream stream. `with` blocks fix this.
- **Assuming the prefill is echoed back.** It isn't — your stored full message must include the prefill yourself if you want it visible (e.g. prepend ` ```json ` to `final.content[0].text` before saving).
- **Trailing whitespace in the prefill.** Anthropic rejects assistant prefills ending in whitespace. End on a non-space character (` ```json `, `<answer>`, `{"`).
- **Stop sequence collides with valid output.** Stopping on `}` truncates nested JSON; stopping on `\n` truncates multi-line content. Pick a sentinel that can't appear inside the desired output, or use a fenced wrapper.
- **Blocking the event loop in async servers.** In FastAPI/Starlette, use `client.messages.stream()` inside an async handler and `async for` over `text_stream` (the SDK supports both sync and async forms).
- **Checking `stop_reason` only on success path.** When using `stop_sequences`, verify `final.stop_reason == "stop_sequence"`. If it's `"end_turn"` or `"max_tokens"`, your output may be incomplete or include unexpected content — that's a bug to fix, not ship.

## Verifying It Works

After integrating, confirm:

1. First chunk reaches the client in < 1s (otherwise streaming isn't actually plumbed through your server — likely a buffering proxy or a non-flushed response).
2. `final_message.stop_reason` matches expectations (`"end_turn"` for normal, `"stop_sequence"` when using `stop_sequences`, `"max_tokens"` if you hit the limit).
3. Token counts in `final_message.usage` are non-zero and roughly match the visible output.
