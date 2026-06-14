# Patch Generation Legacy Strategy Adaptation

This document records the adaptation of the legacy `PATCH_GENERATION_PROMPT`
strategy set into the current MMAP `patch_generation` optimizer template.
It is intentionally text-only — the adaptation was done as a *template content
update only*, with no schema, runtime, or optimizer-loop changes.

## Source Legacy Prompt

- **Name (historical)**: `PATCH_GENERATION_PROMPT`
- **Purpose**: Given a prompt structure, current prompt text, round context,
  and evaluation summary, produce a list of structured patches.
- **Storage**: legacy archive only — not directly imported into this repo.

## Current Target

- **Module**: `mmap_optimizer/templates/optimizer_prompts.py`
- **Template constant**: `PATCH_GENERATION_TEMPLATE`
- **Registry key**: `patch_generation`
- **Output contract** (unchanged):
  - `patches: Patch[]` — zero or more patch objects
  - `cited_sections: string[]` — section identifiers referenced by patches
- **Fallback** (unchanged): `{"patches": [], "cited_sections": []}`
- **Input variables** (unchanged):
  - `prompt_structure`
  - `current_prompt`
  - `round_context`
  - `evaluation_summary`

## Migrated Rules

The following rules from the legacy `PATCH_GENERATION_PROMPT` have been
*adapted* (reworded for the current template style) and inserted into
`PATCH_GENERATION_TEMPLATE`:

1. **Success / correct case emits no patch**
   - If the evaluation result indicates the current prompt already handles
     this case correctly, return an empty patch list. Do not invent
     improvements for passing cases.

2. **Four-strategy patch generation framework**
   - **Strategy 1 — Add missing constraint**: missing rule, condition,
     exception, or output requirement.
   - **Strategy 2 — Refine ambiguous instruction**: vague, overly broad,
     conflicting, or easy-to-misinterpret rules.
   - **Strategy 3 — Add localized example or counterexample**: rules that
     need concrete examples / boundary cases to be correctly applied.
   - **Strategy 4 — Tighten output format / decision contract**: invalid
     JSON, wrong label vocabulary, missing fields, malformed structures,
     or inconsistent final answer formats.

3. **Prefer minimal, localized patches**
   - Generate the smallest patch that fixes the observed failure.
   - Prefer editing the most relevant section rather than rewriting broad
     unrelated sections.

4. **Cited-sections guidance**
   - Use `cited_sections` to record the section names referenced by each
     patch (mapped onto the existing `cited_sections` field of the
     output contract; no new field introduced).

5. **Protected / frozen section awareness**
   - Do not propose edits to protected or frozen sections. If the failure
     lies inside a protected section, explain the limitation and return an
     empty patch list instead.

6. **Operation selection priority**
   - Use only operations supported by the current patch schema.
   - Prefer the least invasive supported operation.
   - Do not invent operation names.

7. **No hallucinated evidence**
   - Only generate patches grounded in the provided failure reason, result
     content, ground truth, and current prompt structure. Do not infer
     missing requirements from outside the provided context.

A short **Migration Note** block has been added at the end of the template
so operators reading the rendered prompt can see which parts are legacy
adaptations.

## Rules Not Migrated

The following items from the legacy prompt were *intentionally* left out:

- **New required output fields**: the legacy prompt envisioned optional
  fields such as `confidence` and `rationale_cardinality`. These are not
  migrated because the current output contract is intentionally fixed.
- **Schema changes**: no changes were made to the Patch dataclass,
  `OptimizerTemplateSpec`, or the output schema.
- **New operations**: no new `op` values were introduced.
- **Evaluator semantics**: the evaluator contract is unchanged; the
  adaptation only improves how patch suggestions are produced from
  evaluator output.
- **Direct copy of the legacy prompt wholesale**: the legacy prompt text
  was not pasted verbatim. Instead, its strategy rules were paraphrased
  and integrated into the existing Chinese + English mixed style of the
  current template.

## Contract Preservation

- **JSON output schema**: unchanged. Output is still a JSON object with
  required keys `patches` and `cited_sections`.
- **Patch `op` vocabulary**: unchanged — the same supported `op` values
  continue to be the only legal values.
- **Placeholders / input variables**: unchanged — the four input
  placeholders remain identical.
- **Registry id / version**: unchanged — `patch_generation` at version
  `1.0`.
- **Fallback value**: unchanged — `{"patches": [], "cited_sections": []}`.

## Risk

- **Risk level**: **medium**
- **Rationale**: the adaptation only adds guidance content to the
  template, so it cannot break the optimizer loop or the patch applier.
  However, changing the patch-generation strategy *can* change the shape
  and distribution of generated patches, so downstream eval curves and
  A/B results may shift. The suggested rollout is:
  1. Keep this template as-is with the legacy rules embedded.
  2. Run the optimizer end-to-end against the current scenario suite and
     compare patch volume / convergence with the prior version.
  3. Only adopt broadly after the real optimizer A/B eval confirms no
     regressions.

## Tests

Contract tests for the adapted template live at:

- `tests/test_optimizer_prompt_patch_generation_template.py`

These tests verify:

- Template existence and render with required placeholders.
- Output contract keys are preserved (`patches`, `cited_sections`).
- All seven migrated rules are present in the rendered template text.
- No unsupported `op` tokens, no new required fields, and no references
  to optimizer-loop or evaluator-semantics changes.
- Other templates (`patch_semantic_merge`, `patch_root_audit`,
  `patch_translation`, `json_fix`) were not modified by this change.

Run with:

```
python -m pytest tests/test_optimizer_prompt_patch_generation_template.py -q
```
