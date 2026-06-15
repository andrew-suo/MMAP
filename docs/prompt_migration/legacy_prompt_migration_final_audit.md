# Legacy Prompt Migration Final Audit

> **Audit date**: 2026-06-15
> **Branch**: `codex/finalize-legacy-prompt-migration-audit`
> **Status**: **docs/tests-only** — no production behavior changes

## Scope

This document provides a final audit and coverage matrix for all 18 legacy prompt templates that were analyzed for migration to the MMAP architecture. It confirms that every legacy prompt has been accounted for with a clear disposition and no ambiguous status remains.

**No production prompt behavior is changed by this final audit.**

## Source Prompt Inventory

Total legacy prompts analyzed: **18**

These prompts were extracted from the user's past project and categorized by capability:

1. Evaluation family: `EVALUATION_PROMPT`, `EVAL_PATCH_GENERATION_PROMPT`
2. Patch generation family: `PATCH_GENERATION_PROMPT`, `PATCH_MERGE_PROMPT`, `PATCH_ROOT_MERGE_PROMPT`
3. Patch translation family: `PATCH_TRANSLATION_PROMPT`, `PATCH_TRANSLATION_RETRY_PROMPT`, `PATCH_TEXT_MATCH_PROMPT`
4. Format/structure family: `PROMPT_REPLACE_SECTION_TEMPLATE`, `JSON_FIX_PROMPT`, `PROMPT_FORMAT_REPAIR_PROMPT`, `PROMPT_REFACTOR_PROMPT`, `PROMPT_REFACTOR_EVAL_PROMPT`
5. Compression/pruning family: `CONSOLIDATION_PROMPT`, `CONSOLIDATION_EVAL_PROMPT`, `LLM_PRUNE_PROMPT`, `LLM_PRUNE_VALIDATION_PROMPT`
6. Standardization: `PROMPT_STANDARDIZATION_PROMPT`

## Final Coverage Matrix

| # | Legacy prompt | Final status | Current target | Adaptation doc | Test coverage | Production default | Risk level | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | `EVALUATION_PROMPT` | migrated | evaluator prompt | mapping doc | ✅ | enabled | medium | 3-state evaluation integrated |
| 2 | `PATCH_GENERATION_PROMPT` | migrated | `patch_generation` | `patch_generation_legacy_strategy.md` | ✅ | enabled | high | 4-strategy framework added |
| 3 | `EVAL_PATCH_GENERATION_PROMPT` | migrated | eval-guided patch generation | mapping doc | ✅ | enabled | medium | eval-specific patch strategies |
| 4 | `PATCH_MERGE_PROMPT` | migrated | `patch_semantic_merge` | `patch_merge_legacy_strategy.md` | ✅ | enabled | high | 3-dimension merge framework |
| 5 | `PATCH_ROOT_MERGE_PROMPT` | migrated | `patch_root_audit` | `patch_root_audit_legacy_strategy.md` | ✅ | enabled | high | 4-dimension cross-section audit |
| 6 | `PATCH_TRANSLATION_PROMPT` | migrated | `patch_translation` | mapping doc | ✅ | enabled | medium-low | payload immutability rules |
| 7 | `PATCH_TRANSLATION_RETRY_PROMPT` | migrated | `patch_translation_retry` | mapping doc | ✅ | enabled | medium-low | error-context-aware retry |
| 8 | `PATCH_TEXT_MATCH_PROMPT` | migrated | `patch_text_match` | mapping doc | ✅ | enabled | low | verbatim substring matching |
| 9 | `PROMPT_REPLACE_SECTION_TEMPLATE` | migrated | `section_rewrite` | mapping doc | ✅ | enabled | medium | incremental fusion rules |
| 10 | `JSON_FIX_PROMPT` | migrated | `json_fix` | mapping doc | ✅ | enabled | low | RFC 8259 compliance |
| 11 | `CONSOLIDATION_PROMPT` | migrated | `llm_prune` | mapping doc | ✅ | enabled | medium | semantic-preserving compression |
| 12 | `CONSOLIDATION_EVAL_PROMPT` | migrated | `llm_prune_validation` | mapping doc | ✅ | enabled | medium | eval-specific compression |
| 13 | `LLM_PRUNE_VALIDATION_PROMPT` | covered_by_prior_adaptation | `llm_prune_validation` | `llm_prune_legacy_strategy.md` | ✅ | enabled | low | covered by consolidation |
| 14 | `LLM_PRUNE_PROMPT` | covered_by_prior_adaptation | `llm_prune` | `llm_prune_legacy_strategy.md` | ✅ | enabled | medium | covered by consolidation |
| 15 | `PROMPT_REFACTOR_PROMPT` | migrated | `prompt_numbering_refactor` | mapping doc | ✅ | enabled | low | numbering-only refactoring |
| 16 | `PROMPT_REFACTOR_EVAL_PROMPT` | not_separately_migrated | n/a | mapping doc | ✅ | n/a | low | no LLM-driven eval target |
| 17 | `PROMPT_FORMAT_REPAIR_PROMPT` | migrated | `prompt_format_repair` | mapping doc | ✅ | enabled | medium-low | heading hierarchy rules |
| 18 | `PROMPT_STANDARDIZATION_PROMPT` | scenario_gated_only | `prompt_standardization` | `prompt_standardization_legacy_strategy.md` | ✅ | disabled | high | must remain opt-in only |

## Migrated Prompts (14)

These 14 legacy prompts have been successfully migrated to their target templates:

1. `EVALUATION_PROMPT` → evaluator prompt
2. `PATCH_GENERATION_PROMPT` → `patch_generation`
3. `EVAL_PATCH_GENERATION_PROMPT` → eval-guided patch generation
4. `PATCH_MERGE_PROMPT` → `patch_semantic_merge`
5. `PATCH_ROOT_MERGE_PROMPT` → `patch_root_audit`
6. `PATCH_TRANSLATION_PROMPT` → `patch_translation`
7. `PATCH_TRANSLATION_RETRY_PROMPT` → `patch_translation_retry`
8. `PATCH_TEXT_MATCH_PROMPT` → `patch_text_match`
9. `PROMPT_REPLACE_SECTION_TEMPLATE` → `section_rewrite`
10. `JSON_FIX_PROMPT` → `json_fix`
11. `CONSOLIDATION_PROMPT` → `llm_prune`
12. `CONSOLIDATION_EVAL_PROMPT` → `llm_prune_validation`
13. `PROMPT_REFACTOR_PROMPT` → `prompt_numbering_refactor`
14. `PROMPT_FORMAT_REPAIR_PROMPT` → `prompt_format_repair`

## Covered By Prior Adaptation (2)

These 2 prompts are fully covered by the consolidation adaptation from PR #74:

1. `LLM_PRUNE_PROMPT` — fully subsumed by `CONSOLIDATION_PROMPT` → `llm_prune`
2. `LLM_PRUNE_VALIDATION_PROMPT` — fully subsumed by `CONSOLIDATION_EVAL_PROMPT` → `llm_prune_validation`

No independent migration is needed or performed for these prompts.

## Scenario-Gated Only (1)

This prompt remains scenario-gated and disabled by default:

1. `PROMPT_STANDARDIZATION_PROMPT` → `prompt_standardization`

**Must NOT be enabled by default** — requires explicit scenario configuration and A/B testing.

## Not Separately Migrated (1)

This prompt is accounted for but not separately migrated:

1. `PROMPT_REFACTOR_EVAL_PROMPT` — No LLM-driven eval-specific numbering refactor target exists. The generic numbering utility (`prompt_numbering_refactor`) handles both regular and eval prompts through placeholder protection rules.

## Production Behavior Guardrails

**No production prompt behavior is changed by this final audit.**

The following guardrails are confirmed:

- ✅ No optimizer loop behavior is changed
- ✅ No patch schema or patch applier behavior is changed
- ✅ No new operations, patch intents, evaluator labels, or required fields are introduced
- ✅ `PROMPT_STANDARDIZATION_PROMPT` remains scenario-gated only and must not be default-enabled
- ✅ `LLM_PRUNE_PROMPT` and `LLM_PRUNE_VALIDATION_PROMPT` are accounted for through consolidation adaptation
- ✅ `PROMPT_REFACTOR_EVAL_PROMPT` is accounted for as not separately migrated
- ✅ No seven-section standardization is enabled by default
- ✅ Current IO contracts are preserved for all templates

## Remaining Follow-Up

The following non-migration follow-up items remain:

1. **Run scenario-level A/B tests** for migrated templates to measure behavioral impact
2. **Measure evaluator label agreement** before/after #69/#70 (evaluation prompt adaptations)
3. **Measure patch acceptance/failure rate** after patch chain migrations (#63-#67)
4. **Measure prompt length and semantic retention** after compression changes (#74)
5. **Keep prompt standardization disabled** unless a future scenario explicitly opts in

## Tests

Final audit tests live at:

- `tests/test_legacy_prompt_migration_final_audit.py`

Run with:

```bash
python -m pytest tests/test_legacy_prompt_migration_final_audit.py -q
```

These tests verify:
- All 18 legacy prompts are accounted for
- Every prompt has one of the four valid status values
- No ambiguous status (pending/unknown/todo) remains
- Adaptation doc coverage is documented
- Guardrail statements are present in this document

## Coverage Summary

| Status | Count |
|---|---|
| migrated | 14 |
| covered_by_prior_adaptation | 2 |
| scenario_gated_only | 1 |
| not_separately_migrated | 1 |
| **Total** | **18** |

## PR History

This final audit consolidates the work from PRs #62-#76:

- #62: Legacy prompt mapping document
- #63-#74: Individual prompt migrations
- #75: LLM prune prompts audit (covered by consolidation)
- #76: Prompt standardization audit (scenario-gated only)
- #77: Final migration audit (this PR)
