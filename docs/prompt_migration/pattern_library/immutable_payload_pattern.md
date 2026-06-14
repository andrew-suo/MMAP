# Immutable Payload Pattern

ID: `immutable-payload`
Risk level: **Medium-low**
Default enabled: **false** — this is a pattern library asset, not wired into any default prompt or CLI flow.

## Purpose

Define the contract for a family of prompt transformations where:

1. The **instruction** around a payload can change (different formatting, different ordering, different target language, different output contract).
2. The **payload body** (business content — field values, rule sentences, placeholder tokens, labels, classification categories) is **byte-preserved**.

This pattern is derived from legacy prompts that needed to apply structural changes to a prompt without silently rewriting its business semantics. It is the foundational contract that every higher-level pattern (JSON repair, numbering refactor, incremental fusion) should satisfy.

## Source Legacy Prompts

The pattern is derived from the following legacy prompts referenced in `source_prompt_bundle_analysis.md`:

- `PATCH_TRANSLATION_PROMPT` — the original "只改结构，不改负载" prompt.
- `PATCH_TRANSLATION_RETRY_PROMPT` — the retry path that re-emphasized payload immutability.
- `PATCH_TEXT_MATCH_PROMPT` — its strict verbatim-substring matching implicitly treated payload content as immutable.
- All evaluation-path prompts that required placeholder tokens to survive rewriting.

## When to Use

- When the transformation target is **structural** or **format** (e.g., "re-indent the JSON", "renumber the list", "add a new sentence about X without changing existing sentences").
- When the payload already carries business-critical content: field names, thresholds, labels, class names, expected output values.
- When multiple transformation steps must compose, and you need to guarantee that payload bits do not drift across steps.
- When a `N-in-N-out` contract is necessary (e.g., "3 prompts in, 3 prompts out, each output corresponding to the input at the same position").

## When Not to Use

- When the *actual* intent is to rewrite the payload semantics (e.g., "fix an incorrect label"). Use a different pattern with an explicit, reviewed payload-change contract.
- When the transformation is only a few characters and the payload is trivially small — the pattern still applies, but the overhead of documenting it may not be worth it.
- When the input is not cleanly separable into instruction + payload.

## Core Guardrails

1. **MUTABLE-IMMUTABLE BOUNDARY.** Each transformation must declare what it treats as mutable (instruction scaffolding, formatting, ordering, structural headers) vs. immutable (payload content). The boundary must survive the transformation.
2. **NO SEMANTIC DRIFT IN PAYLOAD.** After the transformation, every sentence that describes behavior, every threshold value, every field name, every placeholder token must still be present.
3. **NO HALLUCINATED BUSINESS RULES.** The transformation must not add new rules, new required fields, or new labels to the payload.
4. **N-IN-N-OUT.** The number of payload units in the output must equal the number in the input. An output unit corresponds 1-to-1 to the input unit at the same position.
5. **ORDER PRESERVATION.** Within each payload unit, the relative order of sentences, rules, and constraints must be preserved.
6. **PAYLOAD DETERMINISTIC.** Given the same input payload, running the transformation twice must produce the same payload bytes.
7. **NO FIELD RENAMING.** Do not rename field names, variable names, class names, label names, status values, category names, etc.
8. **FAILURE MODE EXPLICIT.** If the transformation cannot guarantee payload byte preservation for a given input, it must emit a structured failure marker instead of silently degrading the payload.

## Mutable vs Immutable Boundary

| Mutable (可以改变) | Immutable (必须字节保留) |
|-------------------|-----------------------|
| Markdown heading labels (`## Rules` → `## 4. Constraints & Rules`) | Business rule sentences |
| Whitespace / indentation around rules | Threshold values (`> 0.9`, `≤ 5`) |
| Bullet point style (`*` vs `-` vs `1.`) | Field names in schemas (`confidence`, `status`, `reason`) |
| Section ordering (of sections that contain identical rules) | Placeholder tokens: `{question}`, `{answer}`, `{label}`, `{prediction}`, `{reference}`, `{context}`, `{input}`, `{output}`, `{prompt_text}`, `{evaluation_criteria}` |
| Comment-like text that is not a rule | Label / class / category values |
| Structural headers that are not themselves rule sentences | Numeric decision criteria (`if score > 0.8 then PASS`) |
| Blank lines between sections | Numeric / string payload content |

## Placeholder Protection

The following tokens are protected substrings in the payload. They must appear in the output exactly as they did in the input:

- `{question}`
- `{answer}`
- `{label}`
- `{prediction}`
- `{reference}`
- `{context}`
- `{input}`
- `{output}`
- `{prompt_text}`
- `{evaluation_criteria}`
- Any other token delimited by literal `{` and `}`.

**Protection rule:** placeholder tokens may be **moved** from one line to another as part of a restructuring, but never **renamed**, **deleted**, or **rewritten**. If a placeholder appears inside a sentence, the sentence must still appear in the output with the placeholder intact.

## N-in-N-out Contract

- Input: a list of N payload units (files, sections, objects — whatever the chosen grain).
- Output: a list of exactly N payload units.
- Position k in the output corresponds 1-to-1 to position k in the input.
- A transformation that drops a payload unit, or produces an extra one, is a **contract violation** and must fail with a structured error.
- If the transformation is unable to process payload k without altering its immutable content, it must emit a structured failure for that unit (instead of emitting a silently-modified payload).

## Order Preservation

Within a single payload unit:

- Rules / sentences appear in the same relative order in output as in input.
- Appending new rules after existing ones is allowed (and documented) only when the caller explicitly requests an append — the default behavior is "no append."
- Deleting, moving, or reordering existing rule sentences is forbidden.

## Allowed Transformations

1. **Structural renaming of section headers.** `## Instructions` → `## 2. Core Instructions`, as long as no rule sentence inside the section is modified.
2. **Whitespace normalization.** Trailing whitespace, excessive blank lines, indentation normalization.
3. **Bullet-point style unification.** `*`, `-`, `1.`, `(1)` — unify to a single style chosen by the caller.
4. **List renumbering.** Fixing `1.`, `1.`, `2.` → `1.`, `2.`, `3.` (per the `numbering-only-refactor` pattern, which this pattern composes with).
5. **Output-contract wrapping.** Wrapping the payload in a pre-declared output schema, as long as the payload body is byte-preserved.
6. **Language translation of instruction headers only.** Translating a section header like "Purpose" is allowed if and only if it does not change any rule sentence in the payload.
7. **ICL marker preservation.** Moving `=== ICL示例开始 ===` and `=== ICL示例结束 ===` markers around a preserved block, never dropping or renaming them.

## Forbidden Transformations

1. **Payload semantic change.** Any modification that alters a rule, threshold, field name, label, or classification value.
2. **Hallucinated business rules.** Adding business rules not present in the input payload.
3. **Field / variable renaming.** `confidence` → `score`, `label` → `class`, etc.
4. **Placeholder renaming.** `{question}` → `{q}`, `{output}` → `{out}`.
5. **Rule deletion.** Dropping a rule sentence because it is "redundant."
6. **Rule reordering.** Moving rules around to "improve readability."
7. **Silent override of weak constraints.** Dropping a "soft" rule because the caller seems to want something else.
8. **Silent override of strong constraints.** Same as above, stronger flavor.
9. **M-in-N-out with M != N.** Producing a different number of output payload units than input payload units.
10. **Order reversal within a payload unit.**
11. **Altering ICL content inside `=== ICL示例开始 === ... === ICL示例结束 ===` blocks.**
12. **Altering example values to "similar" values.** Keep example values byte-identical.

## Examples

### Example 1 — Bullet-point style unification.

Input payload unit:

```text
## Constraints
* status must be PASS or FAIL
- confidence is a number in [0, 1]
1. reason must be a non-empty string
(2) at least one piece of evidence must exist
```

Output payload unit (bullet-point style unified to `-`, with numbers renumbered):

```text
## Constraints
- status must be PASS or FAIL
- confidence is a number in [0, 1]
- reason must be a non-empty string
- at least one piece of evidence must exist
```

Notes:

- Every rule sentence is byte-preserved.
- Placeholder tokens: none.
- Order preserved.
- 1-in-1-out contract satisfied.

### Example 2 — Section header renaming with placeholder preservation.

Input payload unit:

```text
## Task
Read the document and output a classification.

## Eval
For each {question}, compare the model's {prediction} against {label}.

## Output
- status: PASS | FAIL
- confidence: [0, 1]
- reason: free-text justification based on {reference}
```

Output payload unit (section header names normalized; placeholder tokens preserved):

```text
## 1. Task Description
Read the document and output a classification.

## 2. Evaluation Procedure
For each {question}, compare the model's {prediction} against {label}.

## 3. Output Contract
- status: PASS | FAIL
- confidence: [0, 1]
- reason: free-text justification based on {reference}
```

## Anti-examples

### Anti-example 1 — Hallucinated business rule.

Input payload unit:

```text
status must be PASS or FAIL
```

Incorrect output:

```text
status must be PASS, FAIL, or UNCERTAIN
```

**Violation**: introduced a new label (`UNCERTAIN`) that was not in the input. This changes the business semantics of the classification task.

### Anti-example 2 — Field renaming.

Input payload unit:

```text
- confidence: [0, 1]
```

Incorrect output:

```text
- score: [0, 1]
```

**Violation**: renamed a field (`confidence` → `score`), which can break downstream consumers of the payload.

### Anti-example 3 — N-in-N-out broken.

Input: 3 payload units.

Incorrect output: 2 payload units (one unit silently absorbed into another).

**Violation**: M-in-N-out with M != N.

### Anti-example 4 — Placeholder tampering.

Input payload unit:

```text
For each {question}, compare the model's {prediction} against {label}.
```

Incorrect output:

```text
For each query, compare the model's answer against the ground truth.
```

**Violation**: placeholder tokens `{question}`, `{prediction}`, `{label}` have been rewritten with non-placeholder prose. This breaks every downstream consumer that expects those token names.

### Anti-example 5 — Silent weak-constraint override.

Input payload unit:

```text
- If confidence < 0.5, label as UNCERTAIN.
- Output must include a reason field.
```

Incorrect output:

```text
- Output must include a reason field.
```

**Violation**: silently deleted a constraint (`confidence < 0.5 → UNCERTAIN`) because it looked "weak."

## Self-check Checklist

Before and after running a transformation, verify:

- [ ] Placeholder tokens (`{question}`, `{answer}`, `{label}`, `{prediction}`, `{reference}`, `{context}`, `{input}`, `{output}`, `{prompt_text}`, `{evaluation_criteria}`) are byte-identical before and after.
- [ ] Number of payload units in == number out.
- [ ] Field names are byte-identical.
- [ ] Label / class / category values are byte-identical.
- [ ] Threshold values are byte-identical.
- [ ] Rule sentences are byte-identical (possibly reformatted with new bullet-point style, but not rewritten).
- [ ] Relative order of rule sentences within each payload unit is preserved.
- [ ] No new business rule has been added that was not present in the input.
- [ ] ICL markers (`=== ICL示例开始 ===`, `=== ICL示例结束 ===`) are preserved at their original boundaries.
- [ ] Example values are byte-identical.
- [ ] Transformation is deterministic: a second run produces the same bytes.

## Failure Mode Documentation

| Failure mode | Trigger | Expected behavior |
|---|---|---|
| Payload boundary not cleanly parseable | Input does not split cleanly into instruction + payload | Emit structured failure: `{ "pattern": "immutable-payload", "version": "1.0", "status": "cannot_apply", "reason": "payload_boundary_ambiguous" }` |
| Placeholder set not a subset of output placeholders | A placeholder token exists in input but not in output (after byte-for-byte comparison) | Emit structured failure: `{ ..., "status": "placeholder_missing", "missing_placeholders": [...] }` |
| Field name renamed | A field name in input does not appear byte-identically in output | Emit structured failure: `{ ..., "status": "field_renamed", "original_field": "...", "observed_field": "..." }` |
| N-in-N-out broken | Number of output payload units != number of input payload units | Emit structured failure: `{ ..., "status": "payload_count_mismatch", "expected": N, "actual": M }` |
| Determinism check fails | Second run of the same transformation on the same input produces different bytes | Emit structured failure: `{ ..., "status": "non_deterministic" }` |

## Test Contract

Every release of this pattern must satisfy the following tests. They are implemented in `tests/test_pattern_library_immutable_payload.py`:

1. **Doc-publishing test.** `docs/prompt_migration/pattern_library/immutable_payload_pattern.md` must exist and declare a version string.
2. **README-registration test.** `docs/prompt_migration/pattern_library/README.md` must reference `immutable-payload` (or `Immutable Payload`) by name.
3. **Default-enabled test.** The doc must declare `Default enabled: false`.
4. **Mutable-vs-immutable boundary section present.** The doc must include a section or block that explicitly names both "mutable" and "immutable" (or equivalent Chinese terms: 可变 / 不可变).
5. **Placeholder protection section present.** The doc must explicitly name and protect the placeholder tokens `{question}`, `{answer}`, `{label}`, `{prediction}`, `{reference}`, `{context}`, `{input}`, `{output}`.
6. **N-in-N-out contract section present.** The doc must include an N-in-N-out or equivalent contract.
7. **Order preservation section present.** The doc must document order preservation.
8. **No-semantic-drift guardrail present.** The doc must forbid payload semantic change.
9. **No-field-rename guardrail present.** The doc must forbid renaming fields / variables.
10. **No-placeholder-tampering guardrail present.** The doc must forbid renaming or deleting placeholders.
11. **No-constraint-deletion guardrail present.** The doc must forbid deleting original constraints or rules.
12. **No-hallucinated-rules guardrail present.** The doc must forbid adding new business rules.
13. **Examples section present.**
14. **Anti-examples section present.**
15. **Self-check checklist section present.**
16. **Test-contract section present.**

## Migration Notes

- Do **not** wire this pattern into the default prompt-production pipeline. It is intended as an opt-in, on-demand utility.
- This pattern composes with: `numbering-only-refactor` (which fixes numbering without touching payload content) and `json-repair-position-valid` (which fixes JSON structure without touching field values).
- The `N-in-N-out` contract is especially important for batch-processing pipelines and should be preserved end-to-end through the whole pipeline, not just a single step.
- Failure modes must be structured (JSON), not prose. This makes the pattern testable: a test can parse the failure JSON and assert that a specific failure mode was detected.
- The pattern is a **prerequisite** for wiring any pattern into a scenario-gated utility. Before a pattern can be enabled for a scenario, its implementation must demonstrate that it preserves the immutable-payload contract on a representative corpus.
