# Patch Translation Legacy Strategy Adaptation

## Source Legacy Prompts

- **PATCH_TRANSLATION_PROMPT** — calibrates patch locator fields to the current prompt structure. Defines the framework for exact section header matching, in-section-only text resolution, payload immutability, N-in-N-out count preservation, verbatim locator requirement, and the zero-hallucination / unresolved-locator fallback. This is a *locator calibration* prompt, not a patch generation prompt.
- **PATCH_TRANSLATION_RETRY_PROMPT** — re-runs calibration for one failed patch using the reported failure info as the primary signal. Enforces the header → in-section hard match → fuse order, forbids guessing, preserves non-locator payload, and guarantees a one-element JSON array output.

## Current Targets

- `mmap_optimizer/templates/optimizer_prompts.py::PATCH_TRANSLATION_TEMPLATE` — registered as `patch_translation`
- `mmap_optimizer/templates/optimizer_prompts.py::PATCH_TRANSLATION_RETRY_TEMPLATE` — registered as `patch_translation_retry`

Both templates were originally concise, Chinese-language calibrators. This migration enriches them with the legacy framework *while keeping the existing Chinese workflow, placeholders, and JSON contract intact*.

## Migrated Rules

### patch_translation

1. **Exact Section Header Calibration** — any fuzzy / paraphrased section reference must be mapped to an exact header string from the provided prompt structure. No invented section names.
2. **In-Section-Only Locator Matching** — after section calibration, `old_text` / `target_text` are resolved strictly inside the calibrated section. No cross-section search.
3. **Payload Immutability** — only locator fields may be corrected. `op`, `operation_mode`, `content`, `patch_text`, `new_text`, `new_content`, `rationale`, `reasoning`, risk metadata — all preserved exactly.
4. **N-in-N-out Count Preservation** — returns exactly the same number of patches as received. No add, delete, split, or merge during translation.
5. **Verbatim Locator Requirement** — resolved `old_text` / `target_text` must be copied verbatim from the current prompt, including punctuation and whitespace.
6. **Zero-Hallucination / Unresolved Locator Fallback** — if no reliable match exists, the patch is kept unchanged and `extra.unresolved_locators` is populated. No guessing.
7. **No Semantic Rewriting** — patch translation is explicitly *not* patch generation, merge, or root audit. Only locator field correction is performed.

### patch_translation_retry

1. **Failure-Info Driven Retry** — `failure_info` is the primary signal. Only the locator problem described by the failure is fixed; the entire patch is not re-interpreted.
2. **Exactly-One Retry Output** — returns a one-element JSON array containing the repaired version of the input patch. No multiple alternatives.
3. **Header → In-Section Hard Match → Fuse Order** — strictly ordered retry: (a) calibrate exact section header, (b) in-section exact match of `old_text` / `target_text`, (c) unresolved fallback via `extra.unresolved_locators`.
4. **No Guessing** — approximate source text must not be guessed. If no reliable match exists, the original patch is preserved and unresolved locator information is surfaced.
5. **Preserve All Non-Locator Payload** — retry may only repair locator-related fields. Operation, intended new_text, reasoning, risk, and any other semantic payload must not be modified.

## Rules Not Migrated

- **No patch schema changes** — the JSON shape of patch objects is unchanged.
- **No new fields** — no new required top-level fields introduced.
- **No new operations** — the set of supported operation names is unchanged.
- **No new patch intents** — translation/retry templates only calibrate locators; they do not author new patches.
- **No semantic patch rewrite** — content, reasoning, and risk metadata pass through unchanged.
- **No patch generation / merge / root audit behavior** — those templates remain the responsibility of their respective legacy-strategy adaptations.
- **No optimizer loop / CLI / scenario changes** — these templates are pure prompt content.

## Contract Preservation

| Aspect | Before | After |
| --- | --- | --- |
| `patch_translation` input placeholders | `{prompt_structure, current_prompt, patches_json}` | unchanged |
| `patch_translation_retry` input placeholders | `{failure_info, prompt_structure, current_prompt, patch_json}` | unchanged |
| `patch_translation` output contract | JSON array of patch objects; `extra.unresolved_locators` on failure | unchanged |
| `patch_translation_retry` output contract | JSON array with exactly one patch object | unchanged |
| Supported operation names | determined by patch schema, not translation templates | unchanged |
| No LLM runtime calls | true — pure string template | true |

## Risk

**Medium-Low.** The change is additive framework phrasing inside two templates. The risk surface is:

- Model attention shift: the added rules might dilute attention on the original Chinese workflow steps. Mitigation: legacy framework sections are placed *before* the original workflow, and the original Chinese workflow remains intact as the operational checklist.
- Phrase-level over-constraint: if downstream evaluators check for exact wording of the original template text, a diff might appear. Mitigation: the original Chinese sections are preserved verbatim — only new English framework sections are prepended.

## Required Follow-Up

- Measure patch application success rate (locator-matched patches that actually apply cleanly) before and after this change. A material drop is a signal to revisit verbatim-vs-fuzzy matching strength.
- Compare retry success rate before/after; retry template only fires when primary translation fails to apply.
- Confirm no downstream consumer changed expectations on output schema shape.

## Tests

`tests/test_optimizer_prompt_patch_translation_templates.py` covers:

- **Template existence / renderability** — both templates are registered, render with required placeholders, and have no undeclared placeholders.
- **Contract preservation** — placeholders and output contract wording are unchanged; no new required output fields; no unknown operation names introduced.
- **patch_translation rule presence** — asserts that each migrated rule appears in the rendered template.
- **patch_translation_retry rule presence** — asserts failure-info signal, one-element array, exact section header, in-section old_text/target_text, no guessing, preserve original patch, preserve non-locator payload, unresolved locator.
- **Guardrails** — templates must not mention optimizer loop, must not introduce new schema, must forbid add/delete/split/merge, and must forbid semantic rewrite.
- **Other-template isolation** — patch_generation, patch_semantic_merge, patch_root_audit, patch_text_match, json_fix remain registerable and renderable with their own framework markers intact.
