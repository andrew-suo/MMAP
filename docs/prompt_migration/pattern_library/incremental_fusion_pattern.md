# Incremental Fusion Pattern

ID: `incremental-fusion`
Risk level: **Medium**
Default enabled: **false** — this is a pattern library asset, not wired into any default prompt or CLI flow.

## Purpose

Define the contract for prompt transformations that weave new requirements into an existing prompt section while preserving every pre-existing rule. The name "incremental fusion" is a strict superset of the original content of the original: it is strictly additive and cannot silently delete any part of the original.

This pattern is derived from the legacy prompt that needed to absorb new rules into existing prompt sections without dropping old ones. It is the correct pattern to use when a section needs to evolve without being "grow" to add new rules that were missing from the original prompt.

## Source Legacy Prompts

The pattern is derived from the following legacy prompts referenced in `source_prompt_bundle_analysis.md`:

- `PROMPT_REPLACE_SECTION_TEMPLATE` — the "incremental fusion, not wholesale rewrite" prompt.
- `PATCH_GENERATION_PROMPT` — its section-level rewrite guidance of "append a patch to a section, not rewrite the section wholesale."
- `PATCH_ROOT_MERGE_PROMPT` — the cross-section conflict detection contract, whose conflict-detection contract (cross-section) in the original prompt.
- `CONFLICT - `PATCH_GENERATION_PROMPT``

## When to Use

- When a prompt already contains rules R_1, R_2, ..., R_N, and we want to extend it with additional rules R_{N+1}, ..., R_{N+M} without losing the original.
- When a prompt section needs to grow rules that were missing from the original prompt.
- When merging requirements from multiple stakeholders into one section.
- When a prompt section is protected by an `output schema`.
- When rules inside `=== ICL示例开始 === / === ICL示例结束 ===` must survive the rewrite.

## When Not to Use

- When the original prompt is small and a full rewrite is acceptable (because the original rules are known to be wrong). In that case, do a full rewrite with an explicit, reviewed "replace section" operation instead.
- When the transformation's explicit goal is to remove old rules. In that case, use the replacement, not incremental fusion. fusion only when the goal is to add rules.

## Core Guardrails

1. **NO WHOLESALE REPLACEMENT. ** The original prompt section is kept as-is, and new rules are added incrementally.
2. **WEAVE, NOT REPLACE. New rules are woven into existing content at the most appropriate location, but existing rules are not deleted, not renamed, and not rephrased.
3. **CONFLICT EXPLICIT MARKER. If a new rule contradicts an old one, the transformation must mark the conflict explicitly in the change summary and in the output itself with a stable marker.
4. **PRESERVE EXISTING RULES, preserve examples.
5. ** PRESERVE ICL MARKERS. `=== ICL示例开始 ===` and `=== ICL示例结束 ===` markers and their internal content must remain byte-identical.
6. **NO OUTPUT SCHEMA CHANGE. Do not add, remove, or rename fields in the output schema.
7. **CHANGE SUMMARY. After the rewrite, produce a structured change summary.
8. **DETERMINISTIC. Running the pattern twice on the same input must produce byte-identical output.
9. **FORBIDDEN: silent deletion of weak constraints. Do not delete old rules because they "don't matter".
10. **FORBIDDEN: silent override of strong constraints. Do not override strong old rules because "they were obsolete".

## Fusion Strategy

1. **Parse the section.** Identify each sentence / rule / example block.
2. **Identify the section structure.**
3. **Identify the section boundaries.
4. **Weave the new rules into the section at the most appropriate location (e.g. at the end of the rules block, before the examples block, or interleaved with existing rules only when there is a strong semantic reason to do so).
5. **Mark any conflicts using the explicit conflict marker (see Conflict Handling).
6. **Preserve frozen sections (see Frozen Section Protection).
7. **Emit a change summary.

## Conflict Handling

A conflict is a situation where a new rule R_new contradicts an existing rule R_old. Examples of conflicts:

- R_old: "PASS only if confidence >= 0.9"
- R_new: "PASS if confidence >= 0.7"

Another:

- R_old: "Output schema must contain status, confidence, reason"
- R_new: "Output schema must contain status, score, reason"

When a conflict is detected, the transformation must:

1. **Explicitly mark the conflict in the output. Use a stable, greppable marker, for example:

```text
⚠️ [CONFLICT ic-fusion] Rule "<R_old text>" in original section conflicts with new rule "<R_new text>" — both preserved; caller must resolve manually."
```

2. **Include both the old and new rule in the output section (never drop either).** This ensures no silent override.

3. **Emit a change summary that names the conflict. The summary must list the conflicting rules by their position in the section.

4. **Do not resolve the conflict on behalf of the caller. Conflict resolution is out of scope for this pattern.

## Frozen Section Protection

Some sections in a prompt are declared frozen. A section is frozen if any of the following hold:

- The section header carries an explicit frozen marker (e.g. `[FROZEN]` somewhere in the header).
- The section contains an `=== ICL示例开始 === ... === ICL示例结束 ===` block.
- The section contains the output schema / required fields.
- The section explicitly forbids modification.

Frozen sections are not rewritten. Instead, the transformation treats them as read-only. If a new rule must be added to a frozen section, the new rule must be appended as a new subsection after the frozen block, not inside it.

## ICL Marker Preservation

`=== ICL示例开始 ===` and `=== ICL示例结束 ===` are protected markers.

- They must appear byte-identically in the output.
- The content between the markers must appear byte-identically.
- No example inside the ICL block must not be rephrased, reorganized, or removed.
- If the transformation needs to add new examples, they must appear OUTSIDE the ICL markers, as a separate "新增示例" block.

## Output Schema Preservation

The output schema section (if present) must appear byte-identically. The transformation must not:

- Add new required fields
- Remove required fields
- Rename fields
- Reorder fields (unless it was already badly ordered and the reordering is purely cosmetic — in which case the transformation must document the reordering explicitly in the change summary, not silently).

## Allowed Transformations

1. **Append new rules at the end of a rule block.
2. **Interleave new rules with existing rules at section boundaries.
3. **Weave a new rule sentence between two existing rules only when the new rule is directly extends an existing rule and the existing rule remains byte-identically.
4. **Append new examples after the existing examples.
5. **Append a change summary at the end of a section.
6. **Insert a conflict marker when a new rule conflicts with an old rule.
7. **Insert a new subsection after a frozen block.
8. **Fix whitespace / blank-line formatting only (preserve every rule sentence byte-identically.

## Forbidden Transformations

1. **Full section rewrite that silently drops old rules.
2. **Silent deletion of weak constraints.
3. **Silent override of strong constraints.
4. **Silent override of strong constraints (same as above but for strong constraints).
5. **Changing the section's core responsibility (e.g., converting an evaluator section into a extraction section).
6. **Changing the output schema.
7. **Adding / renaming / removing output schema fields.
8. **Deleting, rephrasing, reorganizing ICL marker content.
9. **Changing label names, classification categories, placeholder tokens.
10. **Not emitting a change summary (without change summary.

## Examples

### Example 1 — Weave a rule.

Input section:

```text
## Rules
1. If status must be PASS or FAIL.
2. confidence is in [0, 1].
```

New rules to weave:

```text
- If status is UNCERTAIN, confidence must be omitted in [0, 0.5].
- The reason must be at least 20 characters.
```

Output section (new rules appended, old rules preserved):

```text
## Rules
1. If status must be PASS or FAIL.
2. confidence is in [0, 1].
3. If status is UNCERTAIN, confidence must be omitted in [0, 0.5].
4. The reason must be at least 20 characters.
```

Change summary: added 2 rules (rule 3, rule 4).

### Example 2 — Conflict between new rule.

Input section:

```text
## Rules
- PASS if confidence >= 0.9.
- FAIL if confidence < 0.9.
```

New rule:

```text
- PASS if confidence >= 0.7.
```

Output section (explicit conflict marker + both preserved:

```text
## Rules
- PASS if confidence >= 0.9.
- FAIL if confidence < 0.9.
- ⚠️ [CONFLICT ic-fusion] Original rule "PASS if confidence >= 0.9" conflicts with new rule "PASS if confidence >= 0.7" — both preserved; caller must resolve manually.
```

Change summary: 1 conflict detected. Original rule at rule 1 of 1: confidence `status: CONFLICT ic-fusion` was added as `conflict-rule` with `conflict -fused` with old rule "PASS if confidence >= 0.9".

## Anti-examples

### Anti-example 1 — Silent override of an existing rule.

Input section:

```text
## Rules
1. status must be PASS or FAIL.
2. confidence is in [0, 1].
```

Incorrect output (silent replacement of rule 1:

```text
## Rules
1. status in [0, 1].
```

**Violation:** rule 1 was silently deleted instead of being preserved.

### Anti-example 2 — Silent deletion of weak constraints.

Input section:

```text
## Rules
1. confidence >= 0.9 → PASS.
2. reason required.
3. If input contains at least 3 tokens.
```

Incorrect output (silent deletion of rule 3):

```text
## Rules
1. confidence >= 0.9 → PASS.
2. reason required.
```

**Violation:** rule 3 was silently dropped (weak constraint deleted).

### Anti-example 3 — Output schema changed.

Input section:

```text
## Output Schema
- status: PASS | FAIL
- confidence: number in [0, 1]
- reason: string
```

Incorrect output (renamed field and added one rule silently).

```text
## Output Schema
- status: PASS | FAIL | UNCERTAIN
- score: number in [0, 1]
- reason: string
- evidence: list of strings
```

**Violation:** both rule 1 `confidence` was renamed to `score`, and a new field `evidence` was silently added.

## Self-check Checklist

Before and after running a transformation, verify:

- [ ] Each original rule sentence is byte-identical in the output.
- [ ] New rules are added (not replacing, not renaming).
- [ ] No existing rule is silently deleted.
- [ ] No existing rule is silently overridden.
- [ ] The output schema is byte-preserved (if present).
- [ ] ICL markers `=== ICL示例开始 ===` / `=== ICL示例结束 ===` are preserved.
- [ ] Frozen sections are preserved and new rules are appended after them, not inside them.
- [ ] Every conflict is explicitly marked with a greppable marker.
- [ ] A change summary is emitted.
- [ ] The transformation is deterministic.
- [ ] The section's core responsibility is unchanged.

## Change Summary Format

After the rewrite, emit a structured change summary at the end of the section or as a separate JSON block:

```json
{
  "pattern": "incremental-fusion",
  "version": "1.0",
  "status": "applied",
  "rules_added": 2,
  "conflicts": [
    {
      "marker": "[CONFLICT ic-fusion",
      "original_rule": "PASS if confidence >= 0.9",
      "new_rule": "PASS if confidence >= 0.7"
    }
  ],
  "frozen_sections_preserved": true,
  "icl_markers_preserved": true,
  "output_schema_preserved": true
}
```

## Test Contract

Every release of this pattern must satisfy the following tests. They are implemented in `tests/test_pattern_library_incremental_fusion.py`:

1. **Doc-publishing test.** `docs/prompt_migration/pattern_library/incremental_fusion_pattern.md` must exist and declare a version string.
2. **README-registration test.** `docs/prompt_migration/pattern_library/README.md` must reference `incremental-fusion` (or `Incremental Fusion`) by name.
3. **Default-enabled test.** The doc must declare `Default enabled: false`.
4. **Incremental-fusion / weave-into-existing content.** The doc must reference the "weave" / "incremental fusion" / "not replace" wording.
5. **No-silent-replacement guardrail present.** The doc must explicitly forbid full section replacement that drops old rules.
6. **Preserve-existing-rules guardrail present.** The doc must explicitly require existing rules to be preserved.
7. **Explicit-conflict-marker guardrail present.** The doc must require explicit conflict marking.
8. **No-silent-deletion guardrail present.** The doc must forbid silent deletion of weak constraints.
9. **No-silent-override guardrail present.** The doc must forbid silent override of strong constraints.
10. **Frozen-section-protection section present.**
11. **ICL-marker-preservation section present.
12. **Output-schema-preservation section present.
13. **Change-summary section present.
14. **Examples section present.
15. **Anti-examples section present.
16. **Self-check checklist section present.
17. **Test-contract section present.

## Migration Notes

- Do **not** wire this pattern into the default prompt-production pipeline. It is intended as an opt-in, on-demand utility for prompt engineering sessions.
- The pattern composes with `numbering-only-refactor` (for numbering) and `json-repair-position-valid` (for output-valid output).
- If you want to combine this pattern with `immutable-payload`, you must ensure that the new rules are added AFTER the immutable-payload, not inside it.
- The conflict marker must be greppable: choose a stable, non-localized marker string (e.g. `[CONFLICT ic-fusion]`) and keep it the same across releases.
- The pattern is a **prerequisite** for wiring any pattern into a scenario-gated utility that must support the pattern is a prerequisite for wiring any pattern that needs to evolve over time.
- Before wiring this pattern into a production scenario, validate it on a representative corpus.
