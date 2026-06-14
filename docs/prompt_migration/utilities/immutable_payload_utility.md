# Immutable-Payload Validation Utility

**Module:** `mmap_optimizer.prompt.immutable_payload`

**Purpose:** Deterministically check whether a prompt *rewrite* (or *JSON
repair*, *formatting*, *patch translation*) preserves the caller's
"immutable payload" — i.e. business content that must survive prompt
rewriting unchanged, except for a tiny, safe set of whitespace normalizations.

This utility is the **explicit-call** companion to the
[immutable-payload pattern](../pattern_library/immutable_payload_pattern.md).

---

## Relation to Pattern Library

- **Pattern:** immutable-payload pattern (see
  `../pattern_library/immutable_payload_pattern.md`)
- **Utility module:** `mmap_optimizer.prompt.immutable_payload`
- **Default enabled:** **false** *(nothing calls this utility automatically)*
- **Explicit invocation only:** callers must import and call
  `validate_immutable_payload(original, rewritten)` manually.
- **No LLM call:** the utility is a pure text / regex / hash comparison — it
  does not call any model and has no dependency on `mmap_optimizer.model.*`
  or `mmap_optimizer.orchestration.*`.

---

## Explicit invocation only

The utility is intentionally **NOT** wired into the optimizer loop. A prompt
rewrite or JSON repair must be validated *before* being applied to the live
prompt, by the caller. Example:

```python
from mmap_optimizer.prompt.immutable_payload import (
    validate_immutable_payload,
)

# After LLM rewrite / JSON repair / reformatting:
candidate_rewritten = llm_rewrite(original_prompt_text)

# Validate payload preservation *before* committing the change.
result = validate_immutable_payload(original_prompt_text, candidate_rewritten)

if not result.ok:
    print("Refusing rewrite; the following payload issues were detected:")
    for issue in result.issues:
        print(f"  - [{issue.issue_type}] {issue.detail}")
    # Fallback: reject the rewrite, fall back to original_prompt_text.
    # Or: prompt the LLM again with a stricter instruction.
```

---

## Default enabled: false

- `mmap_optimizer.prompt.immutable_payload` is never imported by default
  from any optimizer loop / CLI / scenario code.
- `tests/test_prompt_immutable_payload_utility.py` is the only consumer
  besides manual / explicit scripts.

---

## API

| Symbol | Purpose |
|---|---|
| `validate_immutable_payload(original, rewritten, *, protected_placeholders=None)` | Primary entry point; returns an `ImmutablePayloadValidationResult`. |
| `ImmutablePayloadValidationResult` | Dataclass with `ok: bool`, `issues: tuple[ImmutablePayloadIssue, ...]`, `original_hash: str`, `rewritten_hash: str`. Supports `.to_dict()`. |
| `ImmutablePayloadIssue` | Single issue with fields `issue_type`, `detail`, `payload_id`, `expected`, `actual`. Supports `.to_dict()`. |
| `stable_payload_hash(text: str) -> str` | Deterministic SHA-256 over the *normalized* view of `text` (see below). |
| `normalize_payload_for_comparison(text: str) -> str` | Safe normalization only: line endings, per-line trailing whitespace, and a single trailing newline. Does **not** lowercase, reorder, or remove punctuation. |
| `extract_placeholders(text: str) -> tuple[str, ...]` | Returns every `{name}` token in order (preserves duplicates). |

### Safe normalizations

Applied before comparison (so purely-cosmetic differences cannot produce
false positives):

1. CRLF / CR → LF
2. Per-line trailing space / tab removal
3. Final newline normalization (exactly one trailing `\n`; collapses
   multiple trailing `\n` to one)

### Forbidden normalizations

- ❌ No lowercasing
- ❌ No punctuation removal
- ❌ No line reordering
- ❌ No semantic-level normalization

---

## Examples

### Placeholder preservation

```python
original = "Read the question {question} and provide {answer}."
rewritten = "Please read {question} and write your {answer} below."
result = validate_immutable_payload(original, rewritten)
assert result.ok  # same placeholder set (rule lines differ = ok here,
                  # but if rules are removed we report)
```

### N-in-N-out contract (multi-payload)

```python
original = """
=== PAYLOAD 1 START ===
- First bullet
- Second bullet
=== PAYLOAD 1 END ===

=== PAYLOAD 2 START ===
{{"id": "A", "body": "{content}"}}
=== PAYLOAD 2 END ===
"""

rewritten = """
=== PAYLOAD 1 START ===
- First bullet
- Second bullet
=== PAYLOAD 1 END ===

=== PAYLOAD 2 START ===
{{"id": "A", "body": "{content}"}}
=== PAYLOAD 2 END ===
"""

result = validate_immutable_payload(original, rewritten)
assert result.ok  # two payloads in, two out, content identical.
```

### Bad rewrite detection

```python
original = "{\n  \"answer\": \"{answer}\",\n  \"reasoning\": \"{reasoning}\"\n}"
rewritten = "{\n  \"answer\": \"{answer}\",\n  \"thought\": \"{reasoning}\"\n}"
result = validate_immutable_payload(original, rewritten)
assert not result.ok
# -> field_name_changed issue for "reasoning" / "thought"
```

---

## Limitations

1. **Not a semantic checker.** The utility compares text, not meaning. A
   rephrasing that preserves business intent but uses different wording
   *will* be flagged as a structural change. Callers should treat that as a
   deliberate signal: "this rewrite touches payload text — review it."

2. **Payload block detection is marker-based.** Only payloads wrapped in
   explicit `=== PAYLOAD START ===` / `--- PAYLOAD 1 START ---` markers are
   treated as N-in-N-out blocks. Without markers, the whole input is treated
   as one block (placeholder + structural-line checks still apply).

3. **Only built-in markers are recognized.** Custom markers (e.g.
   `<!-- START PAYLOAD -->`) are not auto-detected; callers can preprocess
   their text before calling the utility.

4. **Placeholders use `{name}` syntax.** The regex matches
   `\{[a-zA-Z_][a-zA-Z0-9_]*\}`. Custom placeholder syntax (e.g. `{{...}}`,
   `<% ... %>`) is not recognized — wrap custom tokens in `{...}` if you
   want them protected, or pass the token names via `protected_placeholders`.

---

## Issue taxonomy

| `issue_type` | Meaning |
|---|---|
| `payload_count_changed` | Original had N payload blocks, rewritten has M ≠ N. |
| `payload_marker_changed` | A `=== PAYLOAD START ===` or similar marker was renamed, reordered, or removed. |
| `placeholder_removed` | A placeholder in the original is missing from rewritten. |
| `placeholder_added` | A placeholder appears in rewritten but was not in the original. |
| `placeholder_reordered` | Same placeholder tokens but in a different order. |
| `field_name_changed` | A JSON-like `"field_name":` token was added or removed. |
| `line_removed` | A markdown heading or rule/list line was removed. |
| `line_added` | A markdown heading or rule/list line was added. |
| `line_count_changed` | Non-empty line count changed by ≥ ~25% and no more specific issue was detected. |
| `hash_changed` | Normalized content hash differs but no more specific issue was detected. |

---

## Safety guardrails

1. **No LLM call.** The module has zero model / orchestration dependencies.
2. **No default integration.** Nothing in the codebase calls this utility
   automatically.
3. **TypeError on bad input.** `validate_immutable_payload(123, "text")`
   raises `TypeError` — it does *not* silently cast to string.
4. **Deterministic.** Same inputs always produce the same result.
5. **Idempotent normalization.** Running `normalize_payload_for_comparison`
   twice produces the same output as running it once.
6. **JSON-serializable report.** `result.to_dict()` → `json.dumps` works.

---

## Test coverage

Tests live in
[tests/test_prompt_immutable_payload_utility.py](file:///workspace/tests/test_prompt_immutable_payload_utility.py)
and cover:

- hash / normalization determinism (9 tests)
- placeholder extraction + default + custom protection (8 tests)
- payload markers: single-block, multi-block, count mismatch, marker
  rename, numbered-order mismatch (5 tests)
- structural-line (heading + rule) preservation (4 tests)
- JSON field name (rename + addition) (2 tests)
- result contract: `ok`, `issues` type, hash fields, `to_dict` → JSON
  round-trip (8 tests)
- guardrails: `TypeError`, empty-string stability, determinism across
  calls, whitespace-only diff is OK, no orchestration/model import, etc.
  (8 tests)

Run:

```bash
python -m pytest tests/test_prompt_immutable_payload_utility.py -q
```
