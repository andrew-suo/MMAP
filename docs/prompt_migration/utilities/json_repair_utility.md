# JSON Repair / Position-Valid Output Utility

**Module:** `mmap_optimizer.prompt.json_repair`

**Purpose:** Deterministic text- / format-level JSON repair. Given text that
may contain Markdown fences, surrounding prose, trailing commas, and
leading / trailing junk characters, return a position-valid JSON string
(parseable by `json.loads`) and a structured `JsonRepairResult` describing
what was done.

Repairs are strictly at the **text / format level** — no semantic field
addition, no inference, no LLM call, no filesystem writes.

---

## Relation to Pattern Library

- **Pattern:** json-repair / position-valid output pattern (see
  `../pattern_library/json_repair_pattern.md`)
- **Utility module:** `mmap_optimizer.prompt.json_repair`
- **Default enabled:** `false` — nothing in the codebase calls this
  utility automatically.
- **Explicit invocation only.** Callers import and call it manually.

---

## Explicit invocation only

Minimal working example:

```python
from mmap_optimizer.prompt.json_repair import repair_json_output, parse_json_strict

raw = '```json\n{"a": 1,}\n```'
result = repair_json_output(raw)

if result.ok:
    assert result.repaired_text == '{"a": 1}'
    value = parse_json_strict(result.repaired_text)
    assert value == {"a": 1}
else:
    for issue in result.issues:
        print(issue.issue_type, "-", issue.detail)
```

Public entry points:

| Function | Purpose |
|---|---|
| `repair_json_output(text)` | Primary entry point. Returns a `JsonRepairResult`. |
| `strip_json_code_fence(text)` | Strip ` ` `` ` json ... ` ` `` ` / ` ` `` ` ... ` ` `` ` only. |
| `extract_position_valid_json_candidate(text)` | Find balanced `{...}` / `[...]` span and drop surrounding prose. |
| `ensure_position_valid_json(text)` | Full text-level pipeline (fence + exterior + trailing comma). |
| `parse_json_strict(text)` | Thin wrapper over `json.loads` — raises `TypeError` on non-str. |

---

## Position-valid contract

For `result.ok == True`:

1. `result.repaired_text.strip()[0]` is `{` or `[`.
2. `result.repaired_text.strip()[-1]` is `}` or `]`.
3. `json.loads(result.repaired_text)` succeeds.
4. No code fences, no prologue, no trailing remarks.

---

## Supported repairs

| Input | Output | Issue emitted |
|---|---|---|
| `` ```json\n{"a":1}\n``` `` | `{"a":1}` | `code_fence_removed` |
| `Here is the JSON: {"a":1} Thanks.` | `{"a":1}` | `exterior_text_removed`, `position_invalid_repaired` |
| `>>> {"a":1} <<<` | `{"a":1}` | `exterior_text_removed`, `position_invalid_repaired` |
| `{"a":1,}` | `{"a":1}` | `trailing_comma_removed` |
| `[1, 2,]` | `[1, 2]` | `trailing_comma_removed` |
| `{"outer":{"inner":1,}}` | `{"outer":{"inner":1}}` | `trailing_comma_removed` |
| `{"name":"日本"}` | unchanged | (no issues — valid JSON) |

---

## Unsupported cases (returns `ok == False`)

| Input | Issue type(s) emitted |
|---|---|
| `{'a': 1}` | `unsupported_single_quotes` |
| `{"a": True, "b": None}` | `unsupported_python_literal` |
| `{a: 1}` | `unsupported_bare_key` |
| `{"a": 1` (unterminated) | `strict_parse_failed` |
| `{"a":1} {"b":2}` | `multiple_json_candidates` |
| `{"x": NaN}` | `strict_parse_failed` |
| `{"a":1 // c}` | `strict_parse_failed` |
| (empty or whitespace only) | `empty_input` |

---

## Issue taxonomy

| Issue type | Meaning |
|---|---|
| `code_fence_removed` | A Markdown code fence surrounded the JSON body and was stripped. |
| `exterior_text_removed` | Prose before or after the JSON span was dropped. |
| `position_invalid_repaired` | Leading / trailing non-JSON characters were trimmed. |
| `trailing_comma_removed` | A trailing comma before `}` / `]` / `)` was removed. |
| `strict_parse_failed` | `json.loads` failed on the repaired text. |
| `multiple_json_candidates` | Multiple top-level `{...}` / `[...]` spans — refusing to pick. |
| `unsupported_single_quotes` | Single-quote JSON detected (not valid JSON). |
| `unsupported_python_literal` | Python `True` / `False` / `None` detected — not JSON. |
| `unsupported_bare_key` | Unquoted object key detected — not valid JSON. |
| `empty_input` | Empty or whitespace-only input. |

---

## Safety guardrails

- **No LLM call.** Zero dependency on `mmap_optimizer.model.*`.
- **No optimizer loop integration.** The utility is never auto-invoked.
- **No CLI integration.** No CLI command references this module.
- **No filesystem writes.** All processing is in-memory.
- **Deterministic output.** Same inputs always produce identical outputs.
- **`TypeError` on non-str inputs.** Protects sloppy callers.
- **Text / format level only.** No field is added, renamed, or removed.
- **No eval / literal_eval.** JSON parsing uses `json.loads` only.

---

## Test coverage

Tests live in
[tests/test_prompt_json_repair_utility.py](file:///workspace/tests/test_prompt_json_repair_utility.py)
and cover 50 cases across four categories:

- **Success tests** (13 cases) — valid object / array JSON preserved,
  fenced stripping works, prose wrapping is removed, trailing comma
  repair, nested trailing comma repair, position-valid contract enforced
  for every success case, parsed values match expected, non-ASCII
  preserved.
- **Failure tests** (12 cases) — empty string, whitespace-only, no JSON,
  Markdown without JSON, single-quote dict, Python True/None literals,
  bare keys, missing closing brace, multiple ambiguous JSON objects,
  NaN, Infinity, comments.
- **Issue contract tests** (12 cases) — each issue type emitted for its
  scenario, plus `issue.to_dict()` stability, `result.to_dict()`
  stability, and JSON serialization round-trip.
- **Guardrail tests** (12 cases) — no model / orchestration / optimizer
  / patch / compression imports, no filesystem writes, `TypeError` on
  non-str input, deterministic across calls, no eval / literal_eval,
  no unknown-field addition, no field rename, array-order preserved,
  direct calls on `strip_json_code_fence`,
  `extract_position_valid_json_candidate`, `ensure_position_valid_json`.

Run:

```bash
python -m pytest tests/test_prompt_json_repair_utility.py -q
```
