# JSON Repair / Position-valid Output Pattern

ID: `json-repair-position-valid`
Risk level: **Low**
Default enabled: **false** — this is a pattern library asset, not wired into any default prompt or CLI flow.

## Purpose

Define the contract for a prompt-transformation utility that takes corrupted or
ill-formed text and produces a **byte-valid JSON** output, while preserving the
semantic field structure of the original.

This pattern is derived from a family of legacy prompts that each expressed the
same idea with slightly different wording:

- **JSON_FIX_PROMPT** — the generic JSON-cleaning prompt used to sanitize model
  outputs before JSON parsing in legacy pipelines.
- **PATCH_TRANSLATION_PROMPT** — its output-validity clause required the final
  emitted text to begin with `{` or `[`, which inspired the position-valid
  contract below.
- **PATCH_TRANSLATION_RETRY_PROMPT** — on retry paths, the model was instructed
  to emit the output *directly* without any surrounding text, which is the origin
  of the "no prose, no code fences" rule.

The pattern below unifies these three into a single, testable contract.

## Source Legacy Prompts

- `JSON_FIX_PROMPT`
- `PATCH_TRANSLATION_PROMPT` (its output-validity section)
- `PATCH_TRANSLATION_RETRY_PROMPT` (its retry rules)
- Any legacy `*_PROMPT` template whose output contract required a pure JSON
  envelope.

## When to Use

- When a model output is expected to be JSON but is wrapped in prose, Markdown
  fences, backticks, or has trailing commentary.
- When a JSON-like payload has been truncated by context-window limits and needs
  to be closed.
- When a patch-generation step in a loop emits a JSON that parses but has minor
  structural defects (trailing commas, unescaped newlines in strings, …).
- When integrating a new prompt template and you want a canonical list of "JSON
  hygiene" checks that must hold.

## When Not to Use

- When the payload is not JSON (e.g., YAML, CSV, free-form). Use format-specific
  patterns instead.
- When you need to change the *semantics* of the JSON: add/remove fields, alter
  values, compute derived fields. This pattern is format-only.
- When the input is already valid JSON. Running this pattern on valid JSON is a
  no-op by design.

## Core Guardrails

1. **POSITION-VALID.** The output's first non-whitespace character must be `{` or
   `[`; the output's last non-whitespace character must be `}` or `]`.
2. **RFC 8259 COMPLIANCE.** The output must parse successfully with a strict
   JSON parser (no trailing commas at array or object end, no unquoted keys,
   no single-quoted strings, no control characters).
3. **NO FENCE, NO PROSE.** The output must not be wrapped in a Markdown code
   fence (``` ``` ```) and must not contain any surrounding prose, explanation,
   or meta-commentary.
4. **FIELD PRESERVATION.** Every field present in the input's parseable part
   (or the best-effort recovered part) must exist in the output, with the same
   key name and a semantically-equivalent value.
5. **NO HALLUCINATION.** Do not infer, invent, or default fields that were
   clearly absent from the input. "Clearly absent" = the field is not mentioned
   anywhere in the text surrounding the JSON fragment.
6. **RECOVERY LOGGING.** If the transformation had to recover from broken
   content, log the repairs in a structured `_meta.repair_trace` field inside
   the output. If the input was clean JSON, the `_meta` field must be omitted.
7. **DETERMINISTIC OUTPUT.** Running the pattern twice on the same input must
   produce byte-identical output.

## Position-valid Output Contract

A text blob `T` is *position-valid JSON* if and only if:

- `strip_leading(T)[0] ∈ {'{', '['}`.
- `strip_trailing(T)[-1] ∈ {'}', ']'}`.
- `json.loads(T)` succeeds with a strict JSON parser.
- There is no non-empty text `P` such that `T = P + real_json_body`
  (prose prefix forbidden) and no non-empty text `S` such that
  `T = real_json_body + S` (prose suffix forbidden).

This definition is intentionally strict: we want to guard against prompts that
produce "mostly JSON" outputs.

## Allowed Repairs

1. **Markdown fence stripping.** If the input is wrapped in triple-backtick
   fences (with or without a language tag like `json`, `jsonl`, `JSON`), strip
   the fences and any blank lines before/after them.
2. **Prose stripping.** If the JSON body is surrounded by explanatory sentences,
   headers, or footers (e.g., `Here is the JSON you asked for: …`,
   `I hope this helps.`), remove the surrounding prose. The resulting text must
   be exactly the JSON body.
3. **Trailing-comma removal.** If an object or array has a trailing comma before
   its closing delimiter, remove it.
4. **Quote normalization.** If JSON keys appear unquoted or single-quoted,
   rewrite them with double quotes. If string values use single quotes, rewrite
   with double quotes.
5. **Bracket / brace closure.** If the JSON is truncated mid-object or
   mid-array, close the missing delimiters. The closure must be the *minimum*
   required to make the JSON parse. Do not invent content inside the closed
   containers.
6. **String escape repair.** Fix unescaped newlines, unescaped literal tabs,
   bare control characters inside JSON strings.
7. **Unicode quote normalization.** If a model produced curly quotes (`"`, `"`)
   in place of ASCII quotes, rewrite them to `"`.
8. **Comma-only line removal.** If an otherwise-valid JSON has a dangling line
   consisting only of `,` or whitespace, remove it.

## Forbidden Repairs

1. **Field addition or renaming.** Never add a field not present in the input.
   The `_meta.repair_trace` field is the *only* exception and is explicitly
   opt-in.
2. **Field value modification.** Never rewrite the value of a string, number,
   or boolean field to "improve" it. Never change `null` to a default value.
3. **Number coercion.** Never convert numbers to strings or vice versa. A value
   like `42` must remain integer `42`, not string `"42"`.
4. **Schema tightening.** Never remove fields even if you judge them "unused."
5. **Inferring absent lists or objects.** Never fill in `[]` or `{}` for
   missing top-level keys. If a key is missing, keep it missing.
6. **Translation or paraphrasing.** Never translate text fields between
   languages, paraphrase, or "improve" wording.
7. **Structure changes.** Never reorder keys, flatten nested structures, or
   hoist sub-objects.
8. **Array pruning.** Never remove elements from arrays.

## Input Contract

- **I1.** Plain text input (UTF-8).
- **I2.** The input may contain valid JSON, a JSON fragment, or prose-enclosed
  JSON. A *JSON fragment* is any string that can be extended or minimally
  repaired into a valid JSON document.
- **I3.** The input must be ≤ 1 MiB.
- **I4.** The caller must pass a `hint` parameter — either `"object"` or
  `"array"` — indicating the expected top-level JSON container type. The
  default is `"object"`.

If I1 or I3 is violated, emit a synthetic JSON `{"error":
"input-violation", "detail": "…"}` with the same `_meta.repair_trace` machinery.

## Output Contract

- **O1.** The output is byte-valid JSON.
- **O2.** The first non-whitespace byte is either `{` (0x7B) or `[` (0x5B).
- **O3.** The last non-whitespace byte is either `}` (0x7D) or `]` (0x5D).
- **O4.** The output is a JSON object if the caller passed `hint: "object"`,
  and a JSON array if the caller passed `hint: "array"`.
- **O5.** The output contains all of the fields that were recoverable from the
  input. "Recoverable" = the text around the field name is consistent with
  that field being present and not explicitly `null`ed.
- **O6.** The output never contains new fields that are not in the input,
  except the optional `_meta.repair_trace` array (see below).
- **O7.** Fields preserve their original JSON type.
- **O8.** When repairs were applied, output must include exactly one top-level
  field `_meta`:
  ```json
  {
    "…original_fields": "…",
    "_meta": {
      "pattern": "json-repair-position-valid",
      "version": "1.0",
      "repair_trace": [
        {"step": "strip-fence", "detail": "removed ```json``` wrapper"},
        {"step": "close-truncation", "detail": "added trailing } and ]"}
      ],
      "source_length": 2841,
      "output_length": 2104
    }
  }
  ```
  If the source JSON parsed correctly without any repair, `_meta` must be
  **omitted** entirely (it is not produced as an empty object). This makes
  it easy to assert at the test level: `assert "_meta" not in parsed` for
  clean inputs.

## Examples

### Example 1 — prose-wrapped JSON.

Input:

```text
Here is the JSON object you asked for:

{
  "status": "ok",
  "confidence": 0.72
}

Let me know if you need more!
```

Output:

```json
{
  "status": "ok",
  "confidence": 0.72,
  "_meta": {
    "pattern": "json-repair-position-valid",
    "version": "1.0",
    "repair_trace": [
      {"step": "strip-prose", "detail": "removed leading and trailing prose"},
      {"step": "parse", "detail": "native parse succeeded"}
    ],
    "source_length": 168,
    "output_length": 119
  }
}
```

### Example 2 — Markdown-fenced JSON.

Input:

```text
```json
{"patches": [{"op": "replace_in_section", "target_section": "## Rules"}]}
```
```

Output (no `_meta` because the body parsed cleanly):

```json
{"patches": [{"op": "replace_in_section", "target_section": "## Rules"}]}
```

### Example 3 — trailing comma and unquoted key.

Input:

```text
{ status: "ok", score: 0.8, }
```

Output:

```json
{"status": "ok", "score": 0.8, "_meta": {"pattern": "json-repair-position-valid", "version": "1.0", "repair_trace": [{"step": "quote-keys", "detail": "quoted unquoted keys"}, {"step": "trailing-comma", "detail": "removed trailing comma in object"}], "source_length": 29, "output_length": 173}}
```

### Example 4 — truncated JSON.

Input:

```text
{"items": [{"id": 1, "name": "first"}, {"id": 2
```

Output (minimum closure — the array and the object must be closed, the
in-progress object `"id": 2` is partial and must either be completed with an
empty string value, or dropped; this pattern chooses to drop partially-formed
objects):

```json
{"items": [{"id": 1, "name": "first"}], "_meta": {"pattern": "json-repair-position-valid", "version": "1.0", "repair_trace": [{"step": "close-truncation", "detail": "closed truncated array; dropped partial object"}], "source_length": 53, "output_length": 185}}
```

## Test Contract

Every release of this pattern must satisfy the following tests. They are
implemented in `tests/test_pattern_library_json_repair.py`.

1. **Doc-publishing test.** `docs/prompt_migration/pattern_library/json_repair_pattern.md`
   must exist and declare a version string.
2. **Position-valid contract text presence.** The document must contain the
   literal phrase `"Position-valid Output Contract"` (case-insensitive header
   match).
3. **First-character rule text.** The document must contain the literal phrase
   `first non-whitespace` and reference `{` or `[` as valid first characters.
4. **Last-character rule text.** The document must contain the literal phrase
   `last non-whitespace` and reference `}` or `]` as valid last characters.
5. **No-fence rule text.** The document must forbid Markdown code fences.
6. **No-prose rule text.** The document must forbid explanatory text around
   the JSON body.
7. **RFC 8259 reference.** The document must reference `"RFC 8259"` by name.
8. **Field-preservation rule.** The document must contain an explicit
   "preservation" / "keep fields" style clause.
9. **No-hallucination rule.** The document must contain an explicit
   "hallucination" / "do not invent" style clause.
10. **Object and Array coverage.** The document must explicitly mention that
    it supports object JSON and array JSON.
11. **Trailing-comma coverage.** The document must mention trailing-comma
    repair.
12. **Fenced-JSON stripping coverage.** The document must mention fenced-JSON
    stripping/decoding.
13. **Example section present.** The document must have an `## Examples`
    section.
14. **Test-contract section present.** The document must have a
    `## Test Contract` section.

## Migration Notes

- Do **not** wire this pattern into the default prompt pipeline. Wrap it as a
  standalone helper that runs only when the default JSON parser fails.
- When used alongside `PATCH_TRANSLATION_PROMPT` style transformations, run
  JSON-repair *last*, after the payload's numbering and section structure are
  finalized.
- Do **not** combine JSON repair with prompt numbering refactor in a single
  pass. Keep the two patterns separate so their test contracts can be verified
  independently.
- Do **not** default-enable the `_meta.repair_trace` field for normal pipeline
  usage. Reserve it for debugging and forensic paths.
- If a caller needs a truly deterministic output (for hashing / versioning),
  the caller must also enforce a canonical key-ordering step *after* this
  pattern runs. This pattern deliberately does not reorder keys.
