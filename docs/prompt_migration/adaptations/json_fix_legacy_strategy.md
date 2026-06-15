# JSON Fix Legacy Strategy Adaptation

## Source Legacy Prompt

- **JSON_FIX_PROMPT** — repairs polluted or malformed JSON back to structurally valid JSON. Defines the framework for syntax-only repair, payload semantics preservation, no schema invention, JSON-only output, minimal edit principle, type preservation, escaping and quote repair, no hallucinated fallback, and contract-aware repair. This is a *pure syntax repair* prompt — not business reasoning, not content generation, not a patch template.

## Current Target

- `mmap_optimizer/templates/optimizer_prompts.py::JSON_FIX_TEMPLATE` — registered as `json_fix`

The original template was a concise Chinese JSON-cleaning template. This migration enriches it with the legacy JSON_FIX_PROMPT framework *while keeping the original Chinese workflow, the single `{raw_text}` placeholder, and the JSON-only output contract intact.*

## Migrated Rules

1. **Syntax-Only Repair** — repair only JSON syntax, escaping, brackets, commas, quotes, and structural validity. Do not change the semantic meaning of the data.
2. **Preserve Payload Semantics** — preserve all original keys, values, array order, object nesting, text content, numbers, booleans, and nulls unless a minimal syntax repair is required.
3. **No Schema Invention** — do not add, remove, or rename fields; do not infer missing business values.
4. **Output JSON Only** — return only the repaired JSON. No explanations, Markdown, code fences, comments, labels, or commentary.
5. **Minimal Edit Principle** — make the smallest possible edit that converts malformed input into valid JSON.
6. **Type Preservation** — preserve value types. Do not convert strings↔numbers, booleans↔strings, arrays↔objects unless original type is unambiguously recoverable.
7. **Escaping and Quote Repair** — fix unescaped quotes, invalid backslashes, trailing commas, missing commas, missing closing brackets, mismatched braces.
8. **No Hallucinated Fallback** — if JSON cannot be reliably repaired, return the most structurally faithful valid JSON representation possible without inventing new semantic content.
9. **Contract-Aware Repair** — use expected output contract only to validate shape and required top-level structure. Do not invent values that were not present in the malformed JSON.

## Rules Not Migrated

- **No output contract changes** — output remains valid JSON only.
- **No new placeholders** — still `{raw_text}` only.
- **No new patch operations** — no op vocabulary introduced.
- **No new patch intents** — json_fix is a pure syntax helper, not a content author.
- **No business reasoning** — the template must not reason about business values.
- **No semantic rewriting** — content and structure semantics are preserved.
- **No explanations / commentary output** — never allowed.
- **No patch template behavior changes** — patch_generation, patch_semantic_merge, patch_root_audit, patch_translation, patch_text_match all unchanged.
- **No optimizer loop / CLI / scenario changes** — pure prompt content only.

## Contract Preservation

| Aspect | Before | After |
| --- | --- | --- |
| Input placeholders | `{raw_text}` | unchanged |
| Output contract | valid JSON, first char `{` or `[` | unchanged |
| Contract type | `json` (fallback `{} or []`) | unchanged |
| No LLM runtime calls | true — pure string template | true |

## Risk

**Low.** The change is additive framework phrasing inside one template, and the original Chinese workflow, placeholder, output contract, and examples are preserved verbatim.

## Tests

`tests/test_optimizer_prompt_json_fix_template.py` covers:

- **Template existence / renderability** — template registered, renders with `raw_text` placeholder, no undeclared placeholders remain.
- **Contract preservation** — placeholders and output contract wording unchanged; output is JSON only; Markdown / code fences explicitly forbidden; no new required fields; no unknown op names.
- **Migrated rule presence** — all nine legacy rules confirmed by phrase-matching in rendered template, including `syntax-only repair`, `preserve payload semantics`, `no schema invention`, `output JSON only`, `minimal edit principle`, `type preservation`, `escaping / trailing commas / missing commas / mismatched braces`, `no hallucinated fallback`, and `contract-aware repair`.
- **Guardrails** — does not mention optimizer loop; does not introduce JSON schema requirements beyond repair; explicitly forbids explanations / commentary; explicitly forbids invented business values; explicitly forbids semantic rewriting.
- **Other-template isolation** — patch_generation, patch_semantic_merge, patch_root_audit, patch_translation, patch_translation_retry, and patch_text_match all still register and render with their own characteristic framework markers intact.
