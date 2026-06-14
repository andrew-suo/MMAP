# Legacy Prompt to MMAP Template Mapping

## Purpose

This document maps the 18 legacy prompt templates (archived in the original prompt bundle) to the current MMAP project templates and modules. Each entry identifies the target, the rules to migrate, the rules to preserve-as-is, a risk rating, default-eligibility, and a minimum test requirement.

**Docs-only mapping. No production prompt changes in this PR.**

## Source Inputs

This mapping is derived from:

- `docs/prompt_migration/source_prompt_bundle_analysis.md` — the archived 18 legacy prompt templates (source-of-truth)
- `docs/prompt_migration/pattern_library/` — reusable design patterns extracted from the legacy bundle
- `docs/prompt_migration/utilities/` — report-only utilities that absorb several legacy behaviors

This document does not paste or reproduce legacy prompt text. It only references the templates by name and maps their structural intent into the current MMAP target modules.

## Mapping Principles

1. **Separate pattern extraction from production prompt replacement.**
   Legacy prompt rules are first abstracted into migration rules, not copied verbatim. A future PR may perform the actual template upgrade; this document is a planning artifact.
2. **Do not default-enable high-risk prompts.**
   `EVALUATION_PROMPT` and `PROMPT_STANDARDIZATION_PROMPT` are tagged `never_without_ab_test` and must not be enabled by default.
3. **Prefer targeted template upgrades.**
   Each adaptation PR should change exactly one current MMAP template — the listed target in the table below.
4. **Preserve current MMAP IO contracts.**
   A legacy prompt's JSON schema, patch schema, or output contract must not be changed because of this mapping unless a separate migration PR explicitly designs a compatible schema migration.
5. **Require A/B or contract tests for behavior-changing templates.**
   Patch generation, patch merge, evaluation prompts, and pruning all require contract tests before their legacy rules can replace current templates.
6. **Docs-only mapping in this PR.**
   No production template is changed by this PR. This PR only documents intended future work.

## Complete Mapping Table

| Legacy prompt | Current MMAP target | Target type | Adaptation strategy | Migrate | Do not migrate | Risk | Default eligible | Required tests |
|---|---|---|---|---|---|---|---|---|
| `EVALUATION_PROMPT` | `mmap_optimizer/evaluation/evaluator.py` evaluation prompt template | `evaluation_template` | `extract_rules_only` | 3-state result idea (CORRECT / INCORRECT / UNCERTAIN); structured reason field; image-vs-extraction cross-check framing; uncertainty preservation | Do not change evaluator from binary to 3-state by default; do not alter scoring semantics; do not change evaluator output contract without separate PR | `high` | `never_without_ab_test` | A/B evaluator output comparison; CORRECT / INCORRECT / UNCERTAIN contract tests; backward compatibility tests |
| `PATCH_GENERATION_PROMPT` | `mmap_optimizer/templates/optimizer_prompts.py::patch_generation` | `optimizer_template` | `direct_template_upgrade` | 4-strategy patch generation framework; PASS/CORRECT → empty patch rule; cited_sections audit field if compatible; explicit operation priority ordering; protected section awareness | Do not change current patch JSON schema unless explicitly planned; do not add unsupported operations; do not force legacy field names if incompatible | `medium` | `never_without_ab_test` | Patch schema compatibility; successful patch application rate; no-op on success cases; cited section consistency if adopted |
| `EVAL_PATCH_GENERATION_PROMPT` | `mmap_optimizer/evaluation/prompt_optimizer.py` | `evaluation_template` | `extract_rules_only` | Eval-prompt specialized root-cause workflow; ground-truth alignment framing; eval_blind_context idea if available in pipeline | Do not change evaluator optimizer output contract by default; do not require eval_blind_context if pipeline does not provide it | `medium` | `never_without_ab_test` | A/B evaluator optimizer output comparison; eval_blind_context conditional tests; root-cause framing regression tests |
| `PATCH_MERGE_PROMPT` | `mmap_optimizer/templates/optimizer_prompts.py::patch_semantic_merge` | `optimizer_template` | `direct_template_upgrade` | 3-dimensional merge framework; group-by-section; logic deduplication; line-level non-overlap; popularity bias as soft signal | Do not delete unique valid patches just because they are rare; do not change patch schema; do not make popularity bias a hard rule | `medium` | `never_without_ab_test` | Duplicate merge tests; conflicting patches tests; unique valid patch preservation; popularity signal softness; JSON array output contract |
| `PATCH_ROOT_MERGE_PROMPT` | `mmap_optimizer/templates/optimizer_prompts.py::patch_root_audit` | `optimizer_template` | `direct_template_upgrade` | Cross-section 4-dimension audit; workflow/rules/output consistency checks; modify-first-never-delete principle; orphan protection | Do not generate new patches in audit; do not silently remove patches; do not block valid section-local patches without evidence | `medium-low` | `never_without_ab_test` | Cross-section conflict detection tests; modify-first behavior tests; no-new-patch-generation tests; no-silent-deletion tests |
| `PATCH_TRANSLATION_PROMPT` | `mmap_optimizer/templates/optimizer_prompts.py::patch_translation` | `optimizer_template` | `direct_template_upgrade` | Exact section header calibration; in-section-only locator search; payload immutability; N-in-N-out count preservation | Do not search locators across sections; do not modify patch op / reasoning / new_text payload; do not add or drop patch items | `medium-low` | `yes` | Exact header match tests; in-section locator search tests; N-in-N-out preservation tests; payload immutability tests; no-match fuse behavior |
| `PATCH_TRANSLATION_RETRY_PROMPT` | `mmap_optimizer/templates/optimizer_prompts.py::patch_translation_retry` | `optimizer_template` | `direct_template_upgrade` | failure_info driven retry; exactly-one retry output; zero-hallucination no-match rule; keep original unchanged if no reliable match | Do not guess locators; do not output multiple retry candidates if contract expects one | `medium-low` | `yes` | Retry on failure tests; single output contract tests; no-match fallback tests; original-preservation tests |
| `PATCH_TEXT_MATCH_PROMPT` | `mmap_optimizer/templates/optimizer_prompts.py::patch_text_match` | `optimizer_template` | `direct_template_upgrade` | Pure substring extraction; de-paraphrasing from intent to source substring; longest meaningful substring rule; empty output on no match | Do not output explanations; do not output JSON if current contract expects raw text; do not guess approximate text | `low` | `yes` | Raw substring output tests; empty output on no match; no explanation tests; format contract tests |
| `PROMPT_REPLACE_SECTION_TEMPLATE` | `mmap_optimizer/templates/optimizer_prompts.py::section_rewrite` | `optimizer_template` | `direct_template_upgrade` | Incremental fusion principle; logic reorganization without replacement; tone/style consistency; no header / no preamble / raw section only | Do not perform full replacement unless explicitly required; do not alter unrelated section constraints; do not output markdown heading if target expects section body only | `medium` | `never_without_ab_test` | Incremental fusion tests; raw-section-body-only tests; no-heading no-preamble tests; unrelated-rule preservation tests |
| `JSON_FIX_PROMPT` | `mmap_optimizer/templates/optimizer_prompts.py::json_fix` + `mmap_optimizer/prompt/json_repair.py` | `prompt_utility` | `keep_as_utility` | RFC 8259 compliance; position-valid output; format A/B detection; no code fence / no preamble | Do not mutate semantic values; do not silently change field names; do not default-run in optimizer unless explicitly configured | `low` | `yes` | RFC 8259 compliance tests; no-fence no-preamble tests; semantic-value preservation tests |
| `CONSOLIDATION_PROMPT` | `mmap_optimizer/compression/engine.py` compression prompt template | `compression_template` | `direct_template_upgrade` | Hard min/max line budget; logic preservation hierarchy; legal dehydration techniques; reverse-recovery when over-compressed | Do not drop core rules; do not compress below min_target_lines; do not remove output format constraints | `medium` | `never_without_ab_test` | Min/max line budget tests; core-rule preservation tests; reverse-recovery tests; placeholder preservation tests |
| `CONSOLIDATION_EVAL_PROMPT` | `mmap_optimizer/compression/engine.py` eval-specific compression template | `evaluation_template` | `extract_rules_only` | Eval placeholder preservation; min/max line budget; preserve evaluation output contract | Do not modify `{{result_content}}` or other eval placeholders; do not alter evaluator semantics | `medium` | `never_without_ab_test` | Placeholder preservation tests; output contract tests; eval vs non-eval differentiation tests |
| `LLM_PRUNE_VALIDATION_PROMPT` | `mmap_optimizer/templates/optimizer_prompts.py::llm_prune_validation` | `optimizer_template` | `extract_rules_only` | 3-criteria validation: semantic completeness / constraint consistency / ambiguity elimination; valid/reason output contract | Do not make pruning stricter by default without regression tests; do not change output schema if current schema differs | `medium-low` | `yes` | Valid/reason schema tests; semantic completeness round-trip tests; ambiguity elimination tests |
| `LLM_PRUNE_PROMPT` | `mmap_optimizer/compression/` pruning prompt template | `compression_template` | `extract_rules_only` | Preserve core task; remove noise; keep imperative constraints; avoid over-compression | Do not remove examples or output format unless explicitly allowed; do not change placeholders | `medium` | `never_without_ab_test` | Compression budget tests; example preservation tests; placeholder preservation tests; over-compression guard tests |
| `PROMPT_REFACTOR_PROMPT` | `mmap_optimizer/prompt/numbering_refactor.py` + `mmap_optimizer/templates/optimizer_prompts.py::prompt_numbering_refactor` | `prompt_utility` | `keep_as_utility` | No-logic-alteration guard; numbering-only scope; minimal change principle | Do not rewrite content; do not change business rules | `low` | `yes` | Numbering-only tests; no-logic-change tests; placeholder preservation tests |
| `PROMPT_REFACTOR_EVAL_PROMPT` | `mmap_optimizer/prompt/numbering_refactor.py` eval numbering refactor path | `prompt_utility` | `keep_as_utility` | Placeholder protection; eval-specific no-logic-change rule; numbering-only scope | Do not modify `{{result_content}}`; do not alter evaluator output contract | `low` | `yes` | Placeholder protection tests; eval-specific no-change tests |
| `PROMPT_FORMAT_REPAIR_PROMPT` | `mmap_optimizer/templates/optimizer_prompts.py::prompt_format_repair` | `pattern_library_only` | `keep_as_pattern` | Markdown heading hierarchy standardization; unique section title rule; dedicated output format section extraction | Do not default-normalize all prompts; do not reorder sections without tests; do not change content semantics | `medium-low` | `no` | Heading hierarchy tests; unique section title tests; content-semantics preservation tests |
| `PROMPT_STANDARDIZATION_PROMPT` | No default target / future scenario-gated normalization only | `scenario_gated_only` | `scenario_gated_only` | 7-section concept as optional standardization: Task Description / Core Instructions / Step-by-Step Reasoning / Constraints & Rules / Output Format / Examples / Additional Guidelines; ICL marker preservation; empty section filler convention | Do not default-change all prompts; do not wire into optimizer loop default path; do not force 7-section structure on current templates; do not merge/split/reorder production prompt sections without A/B tests | `high` | `never_without_ab_test` | Scenario-gated execution tests; 7-section lossless round-trip tests; ICL marker preservation tests |

## Prompt-by-Prompt Adaptation Notes

### 1. `EVALUATION_PROMPT` → evaluation template

The legacy evaluator introduced a 3-state result (`CORRECT / INCORRECT / UNCERTAIN`) and explicit uncertainty preservation. The current evaluator is binary; adapting it changes downstream metric interpretation. **Do not merge as default behavior** — keep behind an opt-in flag and A/B test.

### 2. `PATCH_GENERATION_PROMPT` → `patch_generation`

The legacy 4-strategy framework and cited_sections field are the main areas of overlap with `patch_generation`. The current template already produces a `patches` / `cited_sections` output contract; migration should only refine the guidance text, never the contract.

### 3. `EVAL_PATCH_GENERATION_PROMPT` → evaluation prompt optimizer

An evaluation-flavored variant of patch generation. It shares strategy with `PATCH_GENERATION_PROMPT` but is eval-context aware. Extract the eval-specific ground-truth alignment principle as a rule set; do not merge until `EVALUATION_PROMPT` changes are stabilized.

### 4. `PATCH_MERGE_PROMPT` → `patch_semantic_merge`

The 3-dimensional merge framework (section grouping / logic dedup / line-level non-overlap) and popularity bias are compatible with current `patch_semantic_merge`. Care must be taken that uniqueness of valid patches is preserved.

### 5. `PATCH_ROOT_MERGE_PROMPT` → `patch_root_audit`

Cross-section consistency audit. The modify-first-never-delete principle and orphan protection align well with the current audit template. Refinement should not generate new patches.

### 6. `PATCH_TRANSLATION_PROMPT` → `patch_translation`

Locates legacy patch locators into current prompt sections. The in-section-only rule and payload immutability rule closely match the current template. Low risk, eligible for default.

### 7. `PATCH_TRANSLATION_RETRY_PROMPT` → `patch_translation_retry`

Uses failure_info to produce exactly one retry patch. The zero-hallucination no-match rule must be enforced.

### 8. `PATCH_TEXT_MATCH_PROMPT` → `patch_text_match`

Pure substring extraction. Minimal semantic content; highest-confidence adaptation. Empty output on no match.

### 9. `PROMPT_REPLACE_SECTION_TEMPLATE` → `section_rewrite`

An incremental fusion principle replaces the legacy full-replacement pattern. The raw-section-body-only constraint prevents accidental markdown heading pollution.

### 10. `JSON_FIX_PROMPT` → `json_fix` + `prompt/json_repair.py`

Largely absorbed by the existing `json_repair` utility and template. The remaining legacy rules (RFC 8259, no fence, no preamble) are compatible with the current implementation.

### 11. `CONSOLIDATION_PROMPT` → compression template

The hard min/max line budget and legal dehydration techniques map to current `mmap_optimizer/compression/engine.py` behavior. Reverse-recovery on over-compression is a new rule that requires tests.

### 12. `CONSOLIDATION_EVAL_PROMPT` → eval compression template

Eval-specific compression that must preserve `{{result_content}}` and the eval output contract. Keep as rule extraction only.

### 13. `LLM_PRUNE_VALIDATION_PROMPT` → `llm_prune_validation`

3-criteria validation fits well into the current valid/reason schema. Eligible for default adaptation as a minor upgrade.

### 14. `LLM_PRUNE_PROMPT` → pruning template

Noise removal / constraint preservation. Over-compression avoidance must be tested before default-enabling.

### 15. `PROMPT_REFACTOR_PROMPT` → `prompt_numbering_refactor` utility

Already largely absorbed. The numbering-only scope and no-logic-alteration guard match the current utility design.

### 16. `PROMPT_REFACTOR_EVAL_PROMPT` → eval numbering refactor

Eval placeholder protection variant. Already absorbed via the generic numbering utility.

### 17. `PROMPT_FORMAT_REPAIR_PROMPT` → `prompt_format_repair` pattern

Heading hierarchy standardization and unique section title rule are useful design patterns but should not default-apply to all production prompts.

### 18. `PROMPT_STANDARDIZATION_PROMPT` → scenario-gated only

The 7-section standardization concept is a long-term design goal. It must not be wired into the default optimizer loop. Keep behind scenario-gated configuration.

## Recommended Adaptation Order

### Phase 1 — Current practical optimizer impact

1. `PATCH_GENERATION_PROMPT` → `patch_generation`
2. `PATCH_MERGE_PROMPT` → `patch_semantic_merge`
3. `PATCH_ROOT_MERGE_PROMPT` → `patch_root_audit`
4. `PATCH_TRANSLATION_PROMPT` → `patch_translation`
5. `PATCH_TRANSLATION_RETRY_PROMPT` → `patch_translation_retry`
6. `PATCH_TEXT_MATCH_PROMPT` → `patch_text_match`

### Phase 2 — Section rewrite and compression

7. `PROMPT_REPLACE_SECTION_TEMPLATE` → `section_rewrite`
8. `CONSOLIDATION_PROMPT` → compression
9. `CONSOLIDATION_EVAL_PROMPT` → eval compression
10. `LLM_PRUNE_VALIDATION_PROMPT` → prune validation
11. `LLM_PRUNE_PROMPT` → prune / compression

### Phase 3 — Evaluation semantics, high caution

12. `EVAL_PATCH_GENERATION_PROMPT` → evaluation prompt optimizer
13. `EVALUATION_PROMPT` → evaluator

### Phase 4 — Optional normalization only

14. `PROMPT_FORMAT_REPAIR_PROMPT` → optional format repair
15. `PROMPT_STANDARDIZATION_PROMPT` → scenario-gated only

**Already mostly absorbed:**

- `PROMPT_REFACTOR_PROMPT`
- `PROMPT_REFACTOR_EVAL_PROMPT`
- `JSON_FIX_PROMPT`

## Do-Not-Adapt-Yet List

The following legacy prompts must not be adapted to default paths at this time:

- `PROMPT_STANDARDIZATION_PROMPT` — changes semantics; needs A/B testing; can break downstream comparisons; should be scenario-gated first.
- `EVALUATION_PROMPT` — changes evaluator from binary to 3-state; needs A/B comparison; can break historical metric comparisons; should be opt-in flag only.
- Default extraction prompt replacement — any legacy extraction prompt used as a default should go through the adaptation phases above before being turned on by default.
- Full optimizer loop prompt replacement — replacing more than one optimizer template in a single PR increases risk too much. Use the phase-based adaptation order.

## Testing Requirements by Target

### patch_generation

- Output schema compatibility (`patches`, `cited_sections`)
- No-op on success / CORRECT status
- Supported operation validation
- Protected section behavior
- Patch application success rate

### patch_semantic_merge

- Duplicate merge
- Conflicting patches
- Unique valid patch preservation
- Popularity signal is soft only
- JSON array output

### patch_root_audit

- Cross-section conflict detection
- Modify-first behavior
- No new patch generation
- No silent deletion

### patch_translation / retry

- Exact header match
- In-section locator search
- N-in-N-out preservation
- Payload immutability
- No-match fuse behavior

### patch_text_match

- Raw substring only
- Empty output on no match
- No JSON / no explanation

### section_rewrite

- Incremental fusion
- Raw section body only
- No heading / no preamble
- No unrelated rule removal

### compression

- Min/max line budget
- Reverse recovery
- Placeholder preservation
- Core rule preservation

### evaluator

- 3-state contract
- Backward compatibility
- A/B metric comparison
- Uncertain behavior

## Next PR Candidates

- **PR A:** Adapt `PATCH_GENERATION_PROMPT` into `patch_generation` template
- **PR B:** Adapt `PATCH_MERGE_PROMPT` into `patch_semantic_merge` template
- **PR C:** Adapt `PATCH_ROOT_MERGE_PROMPT` into `patch_root_audit` template
- **PR D:** Adapt `PATCH_TRANSLATION_PROMPT` family into locator templates
- **PR E:** Adapt `PROMPT_REPLACE_SECTION_TEMPLATE` into `section_rewrite` template

**Recommended first actual adaptation PR:**
Adapt `PATCH_GENERATION_PROMPT` into `patch_generation` template. It has the clearest contract overlap with current MMAP (`patches` / `cited_sections`) and the most mature guard rails in the current template.

## Guardrails Statement

- Docs / tests only — no production prompt changes
- No optimizer loop changes
- No CLI changes
- No scenario changes
- No utility changes
- No LLM calls
- No new dependencies
