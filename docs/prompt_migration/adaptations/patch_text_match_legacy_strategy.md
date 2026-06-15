# Patch Text Match Legacy Strategy Adaptation

## Source Legacy Prompt

- **PATCH_TEXT_MATCH_PROMPT** — locates a verbatim source substring from a provided section content, given a potentially paraphrased intent text. Defines the framework for pure substring extraction, de-paraphrasing, longest meaningful substring selection, exact source-copy requirement, in-section-only search, total fuse on no reliable match, field-type sensitivity, no semantic rewriting, and no hallucinated source text. This is a *pure text matching* prompt — not patch generation, not merge, not audit, not translation.

## Current Target

- `mmap_optimizer/templates/optimizer_prompts.py::PATCH_TEXT_MATCH_TEMPLATE` — registered as `patch_text_match`

The original template was a concise Chinese text-matcher. This migration enriches it with the legacy PATCH_TEXT_MATCH_PROMPT framework *while keeping the original Chinese workflow, placeholders, and output contract intact*.

## Migrated Rules

1. **Pure Substring Extraction** — return only the matched substring copied from the provided section content. Do not output explanations, JSON, Markdown, code fences, quotes, labels, or commentary.
2. **De-Paraphrasing from Intent Text to Source Text** — intent_text is a semantic hint only; the output must always come from section_content.
3. **Longest Meaningful Substring Rule** — when multiple candidates match, pick the longest meaningful substring that captures the intended edit target without including unrelated neighboring instructions.
4. **Exact Source-Copy Requirement** — output must be copied verbatim from section_content, preserving original wording, punctuation, and whitespace where relevant.
5. **In-Section Only** — search only within the provided section_content; do not import text from other sections.
6. **Total Fuse on No Reliable Match** — if no reliable match exists, return empty string. Do not guess, paraphrase, synthesize, or repair text. Do not fall back to intent_text.
7. **Field-Type Sensitivity** — field_type is only a hint about locator type (old_text, target_text, insertion anchor). It must not change the output contract.
8. **No Semantic Rewriting** — text matching only; do not rewrite the prompt, generate a patch, merge patches, audit patches, or improve wording.
9. **No Hallucinated Source Text** — never output text that is not present verbatim in section_content.

## Rules Not Migrated

- **No output contract changes** — output remains a plain matched substring; no JSON, no Markdown, no explanation.
- **No new placeholders** — still `{section_content}`, `{intent_text}`, `{field_type}` only.
- **No new patch operations** — no op vocabulary introduced.
- **No new patch intents** — patch_text_match is a pure locator helper, not a content author.
- **No JSON output** — output format is still plain text / empty string.
- **No explanation / commentary output** — only raw substring.
- **Patch generation / merge / audit behavior unchanged** — handled by respective templates.
- **Patch translation / retry behavior unchanged** — handled by respective templates.
- **Optimizer loop / CLI / scenario unchanged** — pure prompt content only.

## Contract Preservation

| Aspect | Before | After |
| --- | --- | --- |
| Input placeholders | `{section_content, intent_text, field_type}` | unchanged |
| Output contract | plain matched substring or empty string | unchanged |
| Contract type | text_or_empty (fallback = `""`) | unchanged |
| Supported operations | none — not a patch generator | unchanged |
| No LLM runtime calls | true — pure string template | true |

## Risk

**Low.** The change is additive phrasing inside one template, and the original Chinese workflow and output contract are preserved verbatim.

## Tests

`tests/test_optimizer_prompt_patch_text_match_template.py` covers:

- **Template existence / renderability** — template registered, renders with required placeholders, no undeclared placeholders remain.
- **Contract preservation** — placeholders and output contract wording unchanged; no JSON output required; no Markdown / code fence output required; no new required fields; no unknown op names.
- **Migrated rule presence** — all nine legacy rules confirmed by phrase-matching in rendered template.
- **Guardrails** — does not mention optimizer loop; does not introduce JSON output contracts; explicitly forbids explanations / commentary; explicitly forbids synthesized text.
- **Other-template isolation** — patch_generation, patch_semantic_merge, patch_root_audit, patch_translation, patch_translation_retry, and json_fix all still register and render with their own characteristic markers intact.
