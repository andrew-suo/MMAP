# Numbering-only Refactor Pattern

ID: `numbering-only-refactor`
Risk level: **Low**
Default enabled: **false** — this is a pattern library asset, not wired into any default prompt or CLI flow.

## Purpose

Define the contract for a prompt-transformation utility that:

1. Repairs malformed numbering / step markers inside iterative prompts
   (both task prompts and evaluation prompts).
2. **Never alters the semantic or business logic of the prompt text.**
3. Preserves format-variable placeholders (see Placeholder Protection) so that
   downstream prompt-application code continues to receive the tokens it expects.

This pattern is an **internal engineering tool** used to normalize prompts that have
become corrupted during iterative auto-patch cycles. It is not intended to rewrite
prompt content for performance or quality reasons.

## Source Legacy Prompts

The pattern is derived from the following legacy prompts referenced in
`source_prompt_bundle_analysis.md`:

- `PROMPT_REFACTOR_PROMPT` — the generic numbering-only refactor prompt used by the
  legacy optimization loop whenever a prompt's enumerated sections had been
  corrupted by patch operations.
- `PROMPT_REFACTOR_EVAL_PROMPT` — the eval-prompt specialization, which additionally
  protected evaluation-scenario placeholders (`{question}`, `{label}`, `{prediction}`,
  …) from accidental renumbering.

## When to Use

- When a prompt has been produced or edited by an automated patching loop and now
  contains duplicated numbered lines (e.g., `1. … 1. … 2. …`), skipped numbers
  (e.g., `1. … 3. …`), or incorrectly nested sub-lists.
- When an evaluation prompt's enumerated instructions have been reordered but the
  evaluator logic depends on the original enumeration.
- When running a regression suite on prompt assets before shipping a new prompt
  version.
- When preparing to refactor the prompt into the 7-section standardization format —
  first normalize the numbering, then normalize the heading hierarchy.

## When Not to Use

- When the numbering in the prompt is **already correct**. Running this pattern on a
  well-formed prompt is a no-op by design, but running it repeatedly wastes budget.
- When the prompt content itself needs to change. This pattern is numbering-only.
- When the transformation requires changing field names, rules, or output structure.
  Use one of the other patterns (JSON repair, patch generation, etc.) instead.
- When working with 7-section standardization. Do not bundle this pattern with
  7-section standardization — run them separately.

## Core Guardrails

Guardrails are written in the imperative because they double as the body of the
reference prompt described under Test Contract.

1. **NO-LOGIC-ALTERATION.** Do not delete, modify, or add any rule, instruction,
   example, or evaluation criteria. The set of sentences describing behavior must
   remain byte-for-byte equivalent after the transformation, after excluding only
   the numbering characters themselves.
2. **NUMBERING-ONLY CHANGES.** Only numbering digits, list markers, and the minimal
   whitespace around them may be modified. Punctuation other than the numeral and
   its immediate `., ), -` prefix must remain untouched.
3. **NO CONTENT RENAMING.** Do not rename variables, rules, sections, labels, or
   field names (`"confidence"`, `"evidence"`, etc.).
4. **NO OUTPUT-FORMAT CHANGE.** Do not modify JSON schemas, field order, required
   fields, or formatting instructions for the downstream output.
5. **PLACEHOLDER PRESERVATION.** Any substring that matches a protected placeholder
   (see Placeholder Protection) must be byte-identical in the output.
6. **NO RULE DELETION.** Do not drop lines, sections, or bullet points that contain
   directive verbs (`must`, `should`, `never`, `do not`, …). If a numbered line
   appears to be semantically empty, preserve it and only correct its number.
7. **NO RULE ADDITION.** Do not add new lines, rules, or examples. Do not invent
   missing sections.
8. **DETERMINISTIC OUTPUT.** Given the same input prompt text, running this pattern
   twice must produce byte-identical output.

## Placeholder Protection

The following tokens are protected substrings. They must appear in the output exactly
as they did in the input, regardless of the surrounding numbering being repaired:

- `{question}` — a prompt query slot.
- `{answer}` — a model-produced answer slot.
- `{label}` — a ground-truth label slot.
- `{prediction}` — a prediction slot for eval prompts.
- `{reference}` — a reference document slot.
- `{context}` — a context/context-window slot.
- `{input}` — a generic input slot.
- `{output}` — a generic output slot.
- `{prompt_text}` — used in eval-prompt-optimizer flows.
- `{evaluation_criteria}` — used in eval-prompt-optimizer flows.
- Any other token bracketed by literal `{` and `}` (e.g., `{status}`).
  Numbering digits inside `{…}` must never be interpreted as list markers.

### Protection Rules

1. Numbering digits appearing **inside** a placeholder (for instance the `1` in
   `{input_1}`) are not considered part of prompt enumeration and must be left
   untouched.
2. If a placeholder token occupies an entire bullet line by accident, the bullet
   marker may be normalized to a consistent `1.`, `2.`, … scheme **only if the
   placeholder body is not touched.**

## Allowed Transformations

1. **Heading / step number normalization.** Ensure each top-level enumerated step
   in the prompt body has a strictly increasing, 1-based index with no gaps.
   `1.`, `2.`, `2.` → `1.`, `2.`, `3.`; `1.`, `3.`, `4.` → `1.`, `2.`, `3.`;
   `2.`, `1.`, `3.` → `1.`, `2.`, `3.`.
2. **Nested-list normalization.** Sub-lists (`1.1.`, `1.2.` or `a)`, `b)`) must
   restart from `1` / `a` under each new parent.
3. **List-style unification.** If a prompt mixes `1.`, `(1)`, `1)`, `1.`, `— ` as
   list markers in the same section, rewrite them to a consistent style that was
   already dominant in that section. Preserve content in each line.
4. **Whitespace trimming.** Trim trailing whitespace per line and collapse
   consecutive blank lines to a single blank line.
5. **Duplicate numbered markers.** When the same number is used for two adjacent
   bullet points because of a copy-paste error, renumber them monotonically.
6. **Markdown heading number normalization.** If headings are numbered like
   `# 1. …`, `# 2. …` and the sequence is broken, preserve the heading text and
   only fix the number.

## Forbidden Transformations

Anything not in the allowed list is forbidden. In particular:

1. **Changing the text of a rule.** Any phrase that expresses behavior, criteria,
   thresholds, or required fields must remain byte-identical.
2. **Deleting a rule.** Even if a numbered line appears redundant, never remove it.
3. **Adding a rule.** Never add a rule. Never introduce new behavior or new required fields.
4. **Renaming a variable or field.** `"confidence"`, `"status"`, `"reason"` and
   similar must keep their exact casing.
5. **Changing the output format contract.** Do not change JSON structure, do not
   change required vs optional, do not change output ordering.
6. **Restructuring sections.** Do not move content between sections, merge sections,
   or split sections.
7. **Touches to placeholders.** Never modify, delete, or move any token of the form
   `{…}`.
8. **Touches to non-English punctuation.** When the prompt uses full-width punctuation
   like `：`, `，`, `。`, leave it untouched unless the punctation is a pure list
   marker.
9. **Formatting changes.** Do not introduce, remove, or change Markdown formatting,
   italics, bold, code fences, etc., outside of the list-marker repair itself.

## Input Contract

A prompt input to this pattern must satisfy:

- **I1.** The prompt is plain text (UTF-8). No binary content.
- **I2.** The prompt contains at least one line beginning with a numbering pattern
  (`1.`, `1)`, `a.`, `§ 1`, or equivalent).
- **I3.** The prompt may contain top-level sections demarcated by Markdown headings
  (`#`, `##`, `###`). These headings may themselves be numbered and are in scope.
- **I4.** When the prompt is an **evaluation prompt**, a JSON field
  `is_eval_prompt: true` is passed through the sidecar to enable placeholder
  protection. The default is `false` when absent.
- **I5.** The prompt is not required to be valid JSON. It is free-form text.

If I1–I3 are violated, the transformation produces an identical copy of the input
(no-op) with status `not-applicable`.

## Output Contract

For each input prompt, the pattern produces a pair:

- `text`: the transformed prompt. Byte-identical to the input except for the
  numbering repairs listed in Allowed Transformations.
- `summary`: a JSON object:
  ```json
  {
    "pattern": "numbering-only-refactor",
    "version": "1.0",
    "applied": true,
    "changes": [
      {"line": 7, "kind": "duplicate-marker-fix", "from": "2.", "to": "3."},
      {"line": 15, "kind": "skip-fix", "from": "4.", "to": "3."}
    ],
    "placeholders_preserved": ["{question}", "{prediction}"],
    "logic_changed": false,
    "content_bytes_before": 1840,
    "content_bytes_after": 1838
  }
  ```

The `summary.logic_changed` must always be `false` for a well-formed application of
this pattern. A test asserting this invariant is in
`tests/test_pattern_library_numbering_refactor.py`.

## Examples

### Example 1 — duplicate numbering.

Input:

```text
## Steps

1. Read the input.
1. Parse the JSON.
2. Emit output.
```

Output:

```text
## Steps

1. Read the input.
2. Parse the JSON.
3. Emit output.
```

### Example 2 — skipped numbers in an eval prompt with placeholders.

Input:

```text
## Evaluation Steps

1. Read {input} carefully.
3. Compare with {label}.
4. Write {prediction}.
5. If {prediction} differs from {label}, mark status = INCORRECT.
```

Output:

```text
## Evaluation Steps

1. Read {input} carefully.
2. Compare with {label}.
3. Write {prediction}.
4. If {prediction} differs from {label}, mark status = INCORRECT.
```

### Example 3 — nested list misnumbered.

Input:

```text
## Strategy

1. Pick a patch.
   3. Examine it.
   5. Apply it.
2. Evaluate.
```

Output:

```text
## Strategy

1. Pick a patch.
   1. Examine it.
   2. Apply it.
2. Evaluate.
```

### Example 4 — mixed list styles.

Input:

```text
- Read the prompt.
(1) Normalize it.
3)  Apply repair.
```

Output (assuming `-` is the dominant style in the enclosing section):

```text
- Read the prompt.
- Normalize it.
- Apply repair.
```

## Test Contract

Every release of this pattern must satisfy the following tests. They are implemented
in `tests/test_pattern_library_numbering_refactor.py`.

1. **Doc-publishing test.** `docs/prompt_migration/pattern_library/numbering_refactor_pattern.md` must exist and declare a version string.
2. **Guardrail text presence.** The document must contain the literal phrases
   `"NO-LOGIC-ALTERATION"`, `"Placeholder Protection"` (case-insensitive header
   match), and `"Forbidden Transformations"`.
3. **Placeholder tokens enumerated.** The document must contain each of:
   `{question}`, `{answer}`, `{label}`, `{prediction}`, `{reference}`,
   `{context}`, `{input}`, `{output}`.
4. **Example section present.** The document must have an `## Examples` section.
5. **Test-contract section present.** The document must have a `## Test Contract`
   section.
6. **No default prompt change.** No file under `prompts/raw/` is modified by this
   PR. The pattern defaults to `disabled: true` in the registry.

## Migration Notes

- Do **not** wire this pattern into the default prompt-production pipeline. It is
  intended as an opt-in, on-demand utility.
- When `PROMPT_REFACTOR_EVAL_PROMPT` is required for an eval-scenario, wrap it in
  a separate, explicitly-named function so the default eval-flow stays untouched.
- Before using this pattern on a prompt already tracked in `prompts/raw/`, first
  commit the prompt as-is, then commit the transformation as a second commit. This
  keeps the diffs reviewable and guarantees no silent content drift.
- This pattern is a **pre-requisite** for 7-section standardization: normalize
  numbering first, then reorganize sections.
