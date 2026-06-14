# Compression Reverse-Recovery Pattern

ID: `compression-reverse-recovery`
Risk level: **Medium**
Default enabled: **false** — this is a pattern library asset, not wired into any default prompt or CLI flow.

## Purpose

Define the contract for prompt transformations that compress a prompt (e.g., consolidate, prune, or shorten it) while maintaining strict semantic fidelity. The defining insight of the pattern is: **compression is not minimization** — it is "maximize semantic fidelity within a budget."

When the output falls below a minimum budget, the pattern requires an explicit **reverse-recovery** (add-back) step before shipping.

This pattern is derived from legacy prompts that expressed:

- **CONSOLIDATION_PROMPT** — line-budget compression with a hard `[min_lines, max_lines]` window.
- **LLM_PRUNE_PROMPT** — the "core死守" rule at the top of the legacy prune prompt.
- **LLM_PRUNE_VALIDATION_PROMPT** — the three-dimension post-compression audit
  (completeness / constraint-preservation / ambiguity-reduction).

## Source Legacy Prompts

- `CONSOLIDATION_PROMPT`
- `CONSOLIDATION_EVAL_PROMPT`
- `LLM_PRUNE_PROMPT`
- `LLM_PRUNE_VALIDATION_PROMPT`

## When to Use

- When prompt output must fit inside a token / line budget and you need a disciplined way to compress.
- When a first-pass compression has made the prompt "too tight" and you need to recover key content before shipping.
- When validating a prompt that was produced by an automated compression step.
- When composing with `immutable-payload` — the compression pattern is the top-of-pipeline pattern; `immutable-payload` is a stricter contract for the payload interior.

## When Not to Use

- When the goal is actually to rewrite the prompt (e.g., change its role, change its domain, change evaluation semantics). Use `incremental-fusion` instead.
- When the goal is removal of a specific rule for a business reason — this is an explicit, reviewable change, not a compression.
- When the prompt is already well within budget and no compression is required — don't run it.

## Core Guardrails

1. **Compression budget contract.** Each run must declare `min_lines`, `target_lines`, and `max_lines` (or equivalent tokens / chars).
2. **Red alert on over-compression.** If the compressed prompt is **below** `min_lines`, the pipeline must enter reverse-recovery; a below-budget output is never silently shipped.
3. **Reverse-recovery priority ordering.** When in recovery, add back items strictly in this priority order:
   1. Hard constraints
   2. Output schema
   3. Decision rules
   4. Edge cases
   5. Examples and ICL markers
   6. Safety and compliance rules
4. **No core logic deletion.** The compression step must not delete core decision logic.
5. **No output-format deletion.** The compression step must not delete the output schema or any output-format constraints.
6. **No placeholder deletion.** `{question}`, `{answer}`, `{label}`, `{prediction}`, `{reference}`, `{context}`, `{input}`, `{output}`, `{prompt_text}`, `{evaluation_criteria}` must survive byte-identically.
7. **No ICL marker deletion.** `=== ICL示例开始 ===` and `=== ICL示例结束 ===` must survive byte-identically.
8. **No rule-generalization.** A concrete rule must not be replaced by a vague, more general rule. "If score >= 0.9 then PASS" must not become "Make a sensible decision based on the score."
9. **Three-dimension semantic audit.** After any compression, run the three-dimension audit: completeness, constraint-preservation, ambiguity-reduction.
10. **Deterministic compression report.** Each run emits a structured report.
11. **No default-prompt replacement.** The pattern ships with `default enabled: false` and must never be wired into the default pipeline without a scenario gate.

## Compression Budget Contract

The budget is declared at the top of the run:

| Field | Meaning | Required |
|-------|---------|----------|
| `original_lines` | line count of the prompt going into compression | Yes |
| `min_lines` | the hard lower bound; output **must not** fall below it | Yes |
| `target_lines` | the ideal line count to aim for | Yes |
| `max_lines` | the hard upper bound; output must not exceed it | Yes |
| `unit` | one of `line`, `token`, `char` (defaults to `line`) | No |

The compression must aim to land inside the closed interval `[min_lines, max_lines]`, ideally near `target_lines`.

## Over-compression Red Alert

If `output_lines < min_lines` after compression, the run enters a **Red Alert**:

1. The compressed prompt is **rejected** from direct output.
2. The pattern automatically enters reverse-recovery (see next section).
3. A `compression_report.risk_level = "RED"` is emitted.
4. A manual reviewer must verify before the prompt is shipped.

## Reverse-Recovery Strategy

When a red alert fires, recover content in the following strict priority order. Each step must be attempted in order. The run exits recovery the moment `min_lines` is achieved and all critical items (hard constraints, output schema, decision rules, edge cases, ICL markers) are present.

1. **Hard constraints** — any line in the original that starts with "must," "must not," "never," "always," "do not," and similar imperative keywords.
2. **Output schema** — the block that defines fields, required fields, JSON output, Markdown tables, etc.
3. **Decision rules** — `if/then`, `when X then Y`, "PASS if / FAIL if" style rules.
4. **Edge cases** — explicit handling of unusual inputs, empty inputs, boundary values, etc.
5. **Examples / ICL markers** — in-line examples and the `=== ICL示例开始 ===` / `=== ICL示例结束 ===` blocks.
6. **Safety / compliance rules** — anything labeled "safety," "compliance," "legal," "privacy."

During recovery, content is **byte-preserved** from the original prompt. Recovery does not rephrase.

## Semantic Audit Criteria

After compression (and any recovery step), run the three-dimension semantic audit:

1. **Completeness.** Every explicit instruction in the original prompt must map to a surviving instruction in the compressed prompt. The surviving instruction must be byte-identical or a byte-shorter, logically-equivalent contraction of the original (e.g., whitespace removal, bullet-style unification).
2. **Constraint-preservation.** Every hard constraint in the original must survive in the compressed prompt with its original keyword set unchanged (e.g., "must," "must not," "never," "always").
3. **Ambiguity reduction.** The compressed prompt must be at least as specific as the original. It must not replace concrete values with vague descriptions, and it must not replace decision branches with catch-all phrasing.

A compression run must emit a `pass` / `warn` / `fail` per dimension and overall. If any dimension is `fail`, the run must not ship without an explicit override.

## Critical Content Preservation

The following items are always classified as critical and must survive in the compressed prompt:

- All placeholder tokens (`{question}`, `{answer}`, `{label}`, `{prediction}`, `{reference}`, `{context}`, `{input}`, `{output}`, `{prompt_text}`, `{evaluation_criteria}`).
- All output-schema lines (JSON field names, required-field markers, output-type markers, examples of the output shape).
- All explicit "must," "must not," "never," "always" lines.
- All decision-rule lines (`if … then PASS / FAIL / UNCERTAIN`).
- All lines marked as `[PROTECTED]` or inside ICL markers.

## ICL Marker Preservation

`=== ICL示例开始 ===` and `=== ICL示例结束 ===` are treated as structural markers. The block between them is a protected prompt region. Compression must not:

- Drop the markers themselves.
- Delete content inside the block (except whitespace normalization).
- Rephrase, translate, or generalize ICL content.
- Reorder lines inside the block.

Allowed: whitespace normalization inside the block, so long as every non-blank line is byte-identical after normalization.

## Compression Report

Every run emits a structured, deterministic report:

```json
{
  "pattern": "compression-reverse-recovery",
  "version": "1.0",
  "unit": "line",
  "budget": {
    "min_lines": 18,
    "target_lines": 22,
    "max_lines": 28
  },
  "original_length": 42,
  "compressed_length": 23,
  "removed_items": [
    { "id": "r1", "kind": "redundant-example", "summary": "duplicate sample-input block" }
  ],
  "preserved_critical_items": [
    { "id": "c1", "kind": "hard-constraint", "summary": "must output JSON" },
    { "id": "c2", "kind": "output-schema",  "summary": "status / confidence / reason" },
    { "id": "c3", "kind": "decision-rule",  "summary": "PASS if score >= 0.9" },
    { "id": "c4", "kind": "icl-marker",     "summary": "=== ICL示例开始 === ... === ICL示例结束 ===" }
  ],
  "recovered_items": [],
  "recovery_was_needed": false,
  "red_alert_fired": false,
  "semantic_audit": {
    "completeness": "pass",
    "constraint_preservation": "pass",
    "ambiguity_reduction": "pass",
    "overall": "pass"
  },
  "risk_level": "GREEN"
}
```

`risk_level` values:

- `GREEN` — landed inside `[min_lines, max_lines]`; all three audit dimensions `pass`.
- `YELLOW` — inside the budget but at least one audit dimension is `warn`.
- `RED` — below `min_lines` or any audit dimension is `fail`.

## Allowed Transformations

1. **Whitespace / blank-line normalization.** Collapse runs of blank lines to a single blank line. Trim trailing whitespace.
2. **Bullet-style unification.** Unify `*`, `-`, `1.`, `(1)` to a consistent style.
3. **Redundant-example removal.** Drop a complete example block only when another block with the same structure and similar values exists, AND the three-dimension audit still passes after removal.
4. **Comment / meta-line removal.** Drop lines that document the prompt-writing process itself rather than what the prompt does (e.g., "Write this list concisely").
5. **Contraction of verbose phrasing.** Replace long, redundant sentences with short, byte-equivalent ones — e.g., "The model is instructed to produce exactly one of three outputs" → "The model produces one of three outputs." Only allowed when the contraction is strictly shorter but logically identical.
6. **Section-header renumbering.** If sections are numbered 1. 2. 2. 4., renumber canonically to 1. 2. 3. 4.
7. **ICL whitespace normalization inside markers.**

## Forbidden Transformations

1. **Deletion of core decision logic.** Never drop a rule that defines the pass / fail / uncertain behavior.
2. **Deletion of output format / output schema constraints.** Never drop output-field names, required-field markers, or output-type markers.
3. **Deletion of placeholder tokens.** Never delete or rename `{question}`, `{answer}`, `{label}`, `{prediction}`, `{reference}`, `{context}`, `{input}`, `{output}`, `{prompt_text}`, `{evaluation_criteria}`.
4. **Deletion of ICL markers or their content.**
5. **Generalization of concrete rules to vague rules.** "PASS if score >= 0.9" must not become "Make a sensible decision based on the score."
6. **Introduction of new rules.** Compression must not add a rule that wasn't present in the original prompt.
7. **Introduction of new fields or schema changes.**
8. **Silent dropping of edge cases.** Every explicit edge case mentioned in the original must survive.
9. **Rephrasing to change tone / style / language.** Compression keeps the same natural language, same tone.
10. **Dropping hard-constraint lines ("must," "must not," "never," "always").**

## Examples

### Example 1 — inside-budget compression.

Input prompt (42 lines):

```text
# Role
You are a classifier.

# Task
Read the input and classify it into one of three classes.
You must output valid JSON with keys status, confidence, reason.
- status is one of PASS, FAIL, UNCERTAIN.
- confidence is a number in [0, 1].
- reason is a short free-text explanation.
The output must start with '{' and end with '}'.

# Rules
- Read the input carefully.
- You must not output any prose before the JSON.
- You must not output any prose after the JSON.
- You must not hallucinate.
- PASS if the input explicitly contains all of the following: ...
- FAIL if any required piece is missing.
- UNCERTAIN if ambiguity remains after careful reading.
- confidence should reflect your certainty in the decision.
... (and so on)
```

Budget: `min_lines=18`, `target_lines=22`, `max_lines=28`.

Compressed prompt (22 lines): header blocks preserved, rule blocks tightened to bullet form, placeholder tokens byte-preserved, ICL markers preserved.

Report: `original_length=42`, `compressed_length=22`, `risk_level=GREEN`, `semantic_audit.overall=pass`.

### Example 2 — red alert and reverse recovery.

Input prompt (38 lines). An over-aggressive first-pass compression produces 12 lines (below `min_lines=18`).

Red alert fires. The pattern enters reverse-recovery in priority order:

1. Add back hard constraints ("must output valid JSON," "must not output prose before JSON").
2. Add back the output schema.
3. Add back the PASS / FAIL / UNCERTAIN decision rules.
4. Add back edge-case handling ("empty input," "ambiguous input").
5. Add back one representative ICL example.
6. Add back compliance rules.

After recovery, length = 20 lines. Report: `red_alert_fired=true`, `recovery_was_needed=true`, `risk_level=YELLOW` (recovered but borderline).

## Anti-examples

### Anti-example 1 — generalized away a concrete threshold.

Original: `"PASS if score >= 0.9."`

Broken compressed version: `"Use your judgment about PASS vs FAIL."`

**Violation:** Concretized decision rule replaced by a vague instruction.

### Anti-example 2 — output schema dropped.

Original: explicitly declares three JSON fields: `status`, `confidence`, `reason`.

Broken compressed version: drops one or more of the three field lines and says, "Output a JSON object."

**Violation:** Output-schema line was a hard constraint and must survive.

### Anti-example 3 — ICL block deleted.

Original prompt has an `=== ICL示例开始 === ... === ICL示例结束 ===` block.

Broken compressed version: deletes the entire block to save space.

**Violation:** ICL markers are protected content; deleting them changes prompt behavior.

### Anti-example 4 — placeholders dropped.

Original: `"classify {input} into one of {classes}."`

Broken compressed version: `"classify the input."`

**Violation:** placeholder tokens are contract; removing them breaks downstream wiring.

## Self-check Checklist

Before shipping a compressed prompt, verify every item:

- [ ] Budget: `min_lines <= compressed_length <= max_lines`.
- [ ] If `compressed_length < min_lines`: red alert fired, reverse-recovery completed, report emitted.
- [ ] All original hard constraints ("must / must not / never / always") survive byte-identically.
- [ ] Output schema survives byte-identically (field names, required-field markers, output-type markers).
- [ ] All placeholder tokens (`{question}`, `{answer}`, `{label}`, `{prediction}`, `{reference}`, `{context}`, `{input}`, `{output}`, `{prompt_text}`, `{evaluation_criteria}`) survive byte-identically.
- [ ] ICL markers survive byte-identically, with their interior byte-identical.
- [ ] No concrete rule has been replaced by a vague generalization.
- [ ] All explicit edge cases survive.
- [ ] Compression report emitted, `risk_level != "RED"` (unless with explicit override).
- [ ] Semantic audit — all three dimensions at least `pass` (or `warn` with documented reason).
- [ ] Run is deterministic — re-running it on the same input yields the same bytes.

## Test Contract

Every release of this pattern must satisfy the following tests. They are implemented in `tests/test_pattern_library_compression_reverse_recovery.py`:

1. **Doc-publishing test.** The pattern doc exists.
2. **README-registration test.** The pattern doc is registered in the library README by name.
3. **Default-enabled-false test.** The doc declares `Default enabled: false`.
4. **Compression-budget test.** The doc documents min / target / max lines.
5. **Over-compression red-alert test.** The doc describes the red-alert behavior.
6. **Reverse-recovery / add-back test.** The doc describes reverse recovery with a priority ordering.
7. **Hard-constraint preservation test.** The doc requires hard constraints to survive.
8. **Output-schema preservation test.** The doc requires the output schema to survive.
9. **Decision-rule preservation test.** The doc requires decision rules to survive.
10. **Placeholder preservation test.** The doc requires placeholder tokens to survive.
11. **ICL-marker preservation test.** The doc requires ICL markers to survive.
12. **No-core-logic-deletion test.** The doc forbids deleting the core decision logic.
13. **No-output-format-deletion test.** The doc forbids deleting the output format.
14. **No-generalization-into-vague-rules test.** The doc forbids replacing concrete rules with vague ones.
15. **Semantic-audit-criteria test.** The doc documents the three-dimension audit: completeness, constraint preservation, ambiguity reduction.
16. **Compression-report test.** The doc documents the compression report structure (original length, compressed length, removed items, preserved critical items, recovered items, risk level).
17. **Examples section present.**
18. **Anti-examples section present.**
19. **Self-check checklist section present.**
20. **Test-contract section present.**

## Migration Notes

- Do **not** wire this pattern into the default prompt-production pipeline. It is intended as an opt-in, on-demand tool.
- The pattern composes with `immutable-payload`: use `compression-reverse-recovery` at the top of the pipeline and `immutable-payload` inside the payload region to ensure byte-fidelity after compression.
- The three-dimension semantic audit defined here is the same family of post-hoc checks used by `LLM_PRUNE_VALIDATION_PROMPT`. Future tooling could share a single audit implementation.
- The red-alert behavior is critical: it makes under-compression visible to humans and prevents accidental shipping of over-compressed prompts.
- Do **not** default-enable the pattern. `default enabled: false` must stay true until an explicit, scenario-gated wiring decision is made.
- Do **not** combine the compression step with a rewrite step in a single pass. Compress first; then — separately and only if needed — run `incremental-fusion` for rule additions.
