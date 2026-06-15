# LLM Prune Legacy Strategy Audit

> **Audit date**: 2026-06-15
> **Branch**: `codex/audit-llm-prune-prompts`
> **Status**: **docs/tests-only** — not separately migrated; covered by #74 consolidation adaptation

## Source Legacy Prompts

| Legacy prompt | Purpose | Input placeholders | Output contract |
|---|---|---|---|
| `LLM_PRUNE_PROMPT` | Section-level text denoising and extreme compression | `{section_header}`, `{section_content}` | Raw compressed section text |
| `LLM_PRUNE_VALIDATION_PROMPT` | Semantic audit of pruned vs original section | `{original_section}`, `{pruned_section}` | `{"valid": boolean, "reason": string}` |

## Current Target

| Target template | Registry key | Purpose |
|---|---|---|
| `LLM_PRUNE_TEMPLATE` | `llm_prune` | Section-level compression with semantic preservation |
| `LLM_PRUNE_VALIDATION_TEMPLATE` | `llm_prune_validation` | Post-compression semantic equivalence validation |

## Relationship To Consolidation Adaptation

**Directly related to — and covered by — PR #74 (`codex/adapt-consolidation-prompts`).**

The legacy `LLM_PRUNE_PROMPT` and `LLM_PRUNE_VALIDATION_PROMPT` are **sibling prompts** to `CONSOLIDATION_PROMPT` / `CONSOLIDATION_EVAL_PROMPT`. All four share the same compression-semantic-preservation discipline:

- `CONSOLIDATION_PROMPT` → `LLM_PRUNE_TEMPLATE` (line-budget variant with min/max lines)
- `CONSOLIDATION_EVAL_PROMPT` → `LLM_PRUNE_VALIDATION_TEMPLATE` (eval-placeholder-aware variant)
- `LLM_PRUNE_PROMPT` → `LLM_PRUNE_TEMPLATE` (plain section compression, no budget constraint)
- `LLM_PRUNE_VALIDATION_PROMPT` → `LLM_PRUNE_VALIDATION_TEMPLATE` (plain section validation, no eval-placeholder awareness)

When #74 merges, it populates `LLM_PRUNE_TEMPLATE` with 10 semantic-preserving compression rules and `LLM_PRUNE_VALIDATION_TEMPLATE` with 4 validation rules. These rules subsume the value of the legacy `LLM_PRUNE_PROMPT` / `LLM_PRUNE_VALIDATION_PROMPT` without introducing independent pruning-specific behavior.

## Migrated Rules

**None — this PR does not independently migrate `LLM_PRUNE_PROMPT` or `LLM_PRUNE_VALIDATION_PROMPT`.**

The value of both prompts is already captured by the consolidation adaptation in #74:

### `LLM_PRUNE_PROMPT` — covered

| Legacy rule | Covered by #74 rule | Status |
|---|---|---|
| Preserve core task / constraint | Rule 1 (semantic-preserving compression) + Rule 2 (preserve all unique constraints) | ✅ covered |
| Remove noise / filler | Rule 9 (minimal wording changes) | ✅ covered |
| Do not add new rules | Rule 1 (only delete/merge; no new content) | ✅ covered |
| Output compressed section body only | Rule 10 (output consolidated section only) | ✅ covered |
| Avoid over-compression | Rule 7 (no over-compression) | ✅ covered |
| Preserve placeholders | Rule 4 (preserve placeholders and variables) | ✅ covered |
| Preserve output contract | Rule 5 (preserve output contract) | ✅ covered |
| Preserve examples unless duplicates | Rule 6 (preserve examples and counterexamples) | ✅ covered |

### `LLM_PRUNE_VALIDATION_PROMPT` — covered

| Legacy rule | Covered by #74 rule | Status |
|---|---|---|
| 3-criteria audit (semantic completeness / constraint consistency / ambiguity elimination) | Rule 1 (evaluate semantic preservation) + Rule 3 (fail on over-compression ambiguity) | ✅ covered |
| Binary valid/reason output | Output contract: `{"valid": boolean, "reason": string}` | ✅ covered |
| Absolute rigor tone | Implied by Rule 2 (fail on semantic loss) | ✅ covered |
| Use existing labels only | Rule 4 (use existing labels only) | ✅ covered |

## Covered By Prior Adaptation

- `LLM_PRUNE_PROMPT` → fully covered by #74 `CONSOLIDATION_PROMPT` → `LLM_PRUNE_TEMPLATE` rules
- `LLM_PRUNE_VALIDATION_PROMPT` → fully covered by #74 `CONSOLIDATION_EVAL_PROMPT` → `LLM_PRUNE_VALIDATION_TEMPLATE` rules

**No independent migration is needed or performed.**

## Rules Not Migrated

All rules from `LLM_PRUNE_PROMPT` and `LLM_PRUNE_VALIDATION_PROMPT` are accounted for by #74. No pruning-specific rules remain unmapped.

Specifically **not** migrated:

- Any output contract changes (contracts are unchanged)
- Any placeholder changes (all preserved as-is)
- Any patch schema changes
- Any new operations or patch intents
- Any optimizer loop changes
- Any evaluator runtime changes
- Any seven-section standardization

## Contract Preservation

### `llm_prune` (LLM_PRUNE_TEMPLATE)

| Element | Status |
|---|---|
| Input placeholders `{section_header}`, `{section_content}` | ✅ unchanged |
| Output contract — raw compressed section text | ✅ unchanged |
| Registry id `llm_prune` | ✅ unchanged |
| Version `1.1` | ✅ unchanged |

### `llm_prune_validation` (LLM_PRUNE_VALIDATION_TEMPLATE)

| Element | Status |
|---|---|
| Input placeholders `{original_section}`, `{pruned_section}` | ✅ unchanged |
| Output contract `{"valid": boolean, "reason": string}` | ✅ unchanged |
| Registry id `llm_prune_validation` | ✅ unchanged |
| Version `1.1` | ✅ unchanged |

## Risk

**Low** — this is a docs/tests-only PR. No template content is modified. The consolidation adaptation in #74 will add rules to these templates upon merge. This audit confirms no independent migration is needed and establishes tests that prevent future accidental duplication.

## Tests

Contract and audit tests for this PR live at:

- `tests/test_llm_prune_legacy_strategy_audit.py`

Run with:

```bash
python -m pytest tests/test_llm_prune_legacy_strategy_audit.py -q
```

Tests verify:

1. **Audit status**: Both `LLM_PRUNE_PROMPT` and `LLM_PRUNE_VALIDATION_PROMPT` are confirmed as covered by the consolidation adaptation — no ambiguous "pending unknown" status.
2. **Contract preservation**: Both `llm_prune` and `llm_prune_validation` templates retain their original placeholders and output contracts.
3. **Rule coverage**: Current templates contain the semantic-preservation, no-over-compression, placeholder-preservation, and fail-on-ambiguity rules that subsume the legacy pruning-specific value.
4. **Guardrails**: Confirms no patch schema changes, no new operations, no optimizer loop modifications, no arbitrary prompt standardization.
5. **Other-template isolation**: Confirms this audit did not touch unrelated templates (patch_generation, patch_semantic_merge, patch_root_audit, patch_translation, patch_text_match, json_fix, section_rewrite, prompt_format_repair, prompt_numbering_refactor).
