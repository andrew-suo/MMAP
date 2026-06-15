# Prompt Standardization Legacy Strategy Audit

> **Audit date**: 2026-06-15
> **Branch**: `codex/audit-prompt-standardization-prompt`
> **Status**: **docs/tests-only with minimal safety fix** — PROMPT_STANDARDIZATION_PROMPT is accounted for but not default-migrated

## Source Legacy Prompt

| Field | Value |
|---|---|
| **Name** | `PROMPT_STANDARDIZATION_PROMPT` |
| **Purpose** | 7-section forced structural normalization |
| **Input** | `{{original_prompt}}` |
| **Output** | Full 7-section standardized prompt |
| **Risk Level** | **High** |
| **Default eligible** | `never_without_ab_test` |

**Legacy behavior**: Maps raw prompts into a canonical 7-section structure:
1. Task Description
2. Core Instructions
3. Step-by-Step Reasoning
4. Constraints & Rules
5. Output Format
6. Examples
7. Additional Guidelines

## Current Target

| Field | Value |
|---|---|
| **Target** | `PROMPT_STANDARDIZATION_TEMPLATE` (registry id: `prompt_standardization`) |
| **Module** | `mmap_optimizer/templates/optimizer_prompts.py` |
| **Status** | Registered but **not wired into default optimizer pipeline** |

## Migration Decision

**NOT default-migrated**. This prompt is documented as **future scenario-gated only**.

The legacy `PROMPT_STANDARDIZATION_PROMPT` attempts whole-prompt structural normalization, including fixed-section formatting. This is higher-risk than format repair or numbering refactor because it can:

- Alter section hierarchy and organization
- Change business logic grouping
- Modify output contract presentation
- Potentially alter prompt semantics if not carefully implemented

## Why Not Default-Migrated

1. **High migration risk**: Would fundamentally change how prompts are structured
2. **Semantic alteration risk**: Normalization can inadvertently change prompt interpretation
3. **Downstream impact**: Could break downstream comparisons and metrics
4. **Needs A/B testing**: Requires extensive validation before production use
5. **Breaking change**: Current prompts are already working; changing their structure risks regressions

## Key Distinctions from Other Templates

- **Not `prompt_format_repair`**: That template does Markdown heading normalization; this does whole-prompt structural reorganization
- **Not `prompt_numbering_refactor`**: That template only fixes numbering; this reorganizes content into 7-section structure
- **Not `section_rewrite`**: That template rewrites individual sections incrementally; this restructures the entire prompt

## Scenario-Gated Future Use

This capability may be enabled in the future **only** when:

- A specific scenario explicitly opts in via configuration
- Full A/B testing has been completed
- No regressions in evaluation metrics are observed
- Documentation is updated to reflect the new behavior
- The template is explicitly marked as `disabled` by default in the registry

## Rules Not Migrated

The following items from the legacy prompt are **intentionally not migrated to default behavior**:

- **7-section canonical structure enforcement** — not enabled by default
- **Automatic whole-prompt standardization** — not wired into optimizer loop
- **Empty section filler convention** (`暂无示例`/`暂无补充说明`) — not applied automatically
- **Section header global uniqueness enforcement** — not enabled by default
- **ICL marker preservation** — available but not required by default

## Contract Preservation

| Element | Status |
|---|---|
| Input placeholder `{original_prompt}` | ✅ preserved |
| Output contract — raw standardized text | ✅ preserved |
| Registry id `prompt_standardization` | ✅ unchanged |
| Version `1.1` | ✅ unchanged |
| Risk level updated to `high` | ✅ fixed |

## Risk

**Risk level**: **High**

**Rationale**: Whole-prompt standardization changes prompt structure, which can alter model behavior and evaluation outcomes. The current implementation is registered in the template registry for potential future use but is **not wired into the default optimizer pipeline**.

**Guardrails**:
- No arbitrary whole-prompt standardization by default
- No seven-section standardization enabled automatically
- Must remain scenario-gated and opt-in only

## Tests

Contract and audit tests for this PR live at:

- `tests/test_prompt_standardization_legacy_strategy_audit.py`

Run with:

```bash
python -m pytest tests/test_prompt_standardization_legacy_strategy_audit.py -q
```

Tests verify:

1. **Audit status**: `PROMPT_STANDARDIZATION_PROMPT` is confirmed as scenario-gated only
2. **Risk level**: Template risk is correctly marked as `high`
3. **No default usage**: Template is not wired into the default optimizer loop or orchestration
4. **Guardrails**: No patch schema changes, no new operations, no optimizer loop modifications
5. **Other-template isolation**: Unrelated templates were not modified

## Migration Note

`PROMPT_STANDARDIZATION_PROMPT` is accounted for but **not default-migrated**. It remains available as a `prompt_standardization` template in the registry but must be explicitly enabled via scenario configuration. The template has been updated with the correct `high` risk level.
