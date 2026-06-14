# Audit Checklist Pattern

ID: `audit-checklist`
Risk level: **Medium-low**
Default enabled: **false** — this is a pattern library asset, not wired into any default prompt or CLI flow.

## Purpose

Define a standardized, structured **pre-ship audit checklist** that a prompt must pass before being used in a pipeline. The checklist is not a quality metric; it is a contract: every item on the list must produce either a `PASS`, `WARN`, or `FAIL`, along with **evidence** and a severity, before the prompt ships.

This pattern is derived from legacy prompts that required the model to self-check its output before emitting it, including the `LLM_PRUNE_VALIDATION_PROMPT` (which audited pruned prompts across three dimensions) and other audit/validation/evaluation/repair prompts in the legacy bundle.

## Source Legacy Prompts

- `LLM_PRUNE_VALIDATION_PROMPT` — the direct ancestor of the three-dimension audit.
- `PATCH_TRANSLATION_RETRY_PROMPT` — the retry-path pattern, which required structured evidence (not a naked `PASS`) before approving a patch.
- `CONSOLIDATION_PROMPT` — whose internal self-check section inspired the evidence requirement.
- All evaluation prompts that required the evaluator to cite evidence for its decision.

## When to Use

- When shipping a new prompt through an automated pipeline and want a deterministic gate.
- After any prompt modification (compression, patch, rewrite, fusion) to confirm behavior is intact.
- After a repair step to verify the fix.
- As a standard pre-execution step for any prompt that affects production outcomes.

## When Not to Use

- When the prompt is a throwaway experiment.
- When the pipeline has no meaningful "output" (e.g., data-exploration prompts).
- When the cost of running the audit exceeds the risk of an undetected bug.

## Core Guardrails

1. **Explicit audit target.** The checklist must declare what prompt / section / output is being audited.
2. **Structured audit dimensions.** Every audit run covers a fixed, named set of dimensions.
3. **Three-valued conclusions.** `PASS`, `WARN`, `FAIL` — never a bare "OK" or "looks good."
4. **Evidence-first.** Every dimension must have **evidence** from the prompt text. A `PASS` without evidence is invalid.
5. **No silent passes.** An auditor must not pass a dimension without examining the relevant prompt text.
6. **Hard-constraint strictness.** Any hard constraint marked in the target (`must`, `never`, `[PROTECTED]`, etc.) must be checked explicitly.
7. **Audit is read-only.** The audit step must not mutate the prompt being audited. If a fix is needed, the audit emits a `FAIL` and a `suggested_fix`; the caller applies the fix in a separate, reviewable step.
8. **Machine-readable output + human-readable explanation.** The audit produces both a deterministic JSON object and a short human-facing summary.
9. **Severity ranking.** Each failing / warning item has a severity: `blocker`, `major`, `minor`, `info`.
10. **Deterministic output.** Same audit inputs produce the same audit output.
11. **Repair recommendation optional.** The audit emits a repair recommendation only when a dimension is `FAIL`.
12. **Default enabled: false.** This pattern must not be wired into the default pipeline without an explicit scenario gate.

## Audit Target

Every audit run must declare its target. Typical targets are:

- A full prompt text.
- A named section within a prompt (e.g., "Rules," "Output format").
- A model output (e.g., a JSON patch, a classification, a text explanation).
- An ICL block.
- A compression report (from the `compression-reverse-recovery` pattern).

## Audit Dimensions

The default dimension set is:

1. **Completeness.** Is every explicit instruction from the original prompt still present?
2. **Constraint-preservation.** Does every hard constraint from the original survive unchanged?
3. **Ambiguity-reduction.** Is the compressed / modified prompt at least as specific as the original — no vagueness introduced?
4. **Output-schema-fidelity.** Does the output schema (as declared) match a canonical reference schema?
5. **Placeholder-preservation.** Are placeholder tokens byte-identical with the reference?
6. **ICL-preservation.** Are ICL markers and their interior byte-identical with the reference?
7. **No-hallucination.** Are no new rules, constraints, or fields introduced in the target?
8. **Determinism-style.** Is the target free of randomness, date-sensitive logic, or non-deterministic phrasing?

A specific run may use a subset of these dimensions, but it must declare which dimensions it is using.

## Pass / Warning / Fail Semantics

- **PASS.** The dimension is fully satisfied. Requires explicit evidence: a direct quote from the prompt, a concrete field check, or a verifiable structural property.
- **WARN.** The dimension is not fully met but the defect is not blocking. Evidence must explain why it is minor. A WARN is a signal for reviewers, not a hard stop.
- **FAIL.** The dimension is violated. Requires evidence, a severity level, and a `suggested_fix`. A FAIL must be resolved before the prompt ships.

A single `FAIL` on any dimension means the overall audit result is `FAIL`.

## Evidence Requirement

Evidence is a required field for every checklist item. Acceptable forms include:

- A verbatim quote from the prompt (with line reference or surrounding context).
- A structural property that can be verified by a machine schema check (e.g., "JSON contains field `status` and its value is one of PASS / FAIL / UNCERTAIN").
- An explicitly-negative observation: "The prompt contains no text matching `{classes}` anywhere; placeholder not required for this prompt."
- A structured before/after diff reference (from an incremental-fusion report).

**Never:** "The prompt looks good," "I don't see any issue," "Nothing to report," or any other zero-evidence claim.

## Checklist Item Schema

Each item in the checklist has this JSON shape:

```json
{
  "id": "c1",
  "dimension": "completeness",
  "status": "PASS",
  "evidence": "The prompt contains the verbatim line 'status must be one of PASS, FAIL, UNCERTAIN'.",
  "issue": null,
  "severity": null,
  "suggested_fix": null
}
```

A failing item example:

```json
{
  "id": "c7",
  "dimension": "no-hallucination",
  "status": "FAIL",
  "evidence": "The compressed prompt includes a line 'Reject high-risk inputs.' that is not present in the reference prompt.",
  "issue": "A new rule has been introduced by the compression step without review.",
  "severity": "major",
  "suggested_fix": "Remove the line 'Reject high-risk inputs.' and rerun the audit."
}
```

## Severity Levels

- **blocker** — the defect changes prompt behavior on the main path; must be resolved before the prompt ships.
- **major** — the defect is likely to cause wrong output in realistic scenarios.
- **minor** — the defect is unlikely to affect main-path behavior but degrades prompt clarity.
- **info** — an observation that is not a defect but is worth recording (e.g., "This prompt contains no examples; consider adding some").

## Failure Summary

If any item has status `FAIL`, the run must produce a failure summary:

```json
{
  "overall": "FAIL",
  "fail_count": 2,
  "warn_count": 1,
  "fail_items": ["c5", "c7"],
  "warn_items": ["c3"]
}
```

## Repair Recommendation

Each failing checklist item includes a `suggested_fix` field that is a short, actionable description of what should change in the target prompt. This field is **machine-readable text only**. It must not be executed automatically; a human reviewer must approve any fix.

## Machine-readable Output

The audit run emits a single JSON object with a fixed top-level shape:

```json
{
  "pattern": "audit-checklist",
  "version": "1.0",
  "audit_target": {
    "kind": "prompt",
    "name": "classification-prompt-v3",
    "reference_checksum": "sha256:..."
  },
  "dimensions_used": ["completeness", "constraint-preservation", "ambiguity-reduction", "output-schema-fidelity", "placeholder-preservation", "icl-preservation", "no-hallucination", "determinism-style"],
  "items": [
    { "id": "c1", "dimension": "completeness", "status": "PASS", "evidence": "...", "issue": null, "severity": null, "suggested_fix": null },
    { "id": "c2", "dimension": "constraint-preservation", "status": "PASS", "evidence": "...", "issue": null, "severity": null, "suggested_fix": null }
  ],
  "failure_summary": { "overall": "PASS", "fail_count": 0, "warn_count": 0, "fail_items": [], "warn_items": [] },
  "repair_recommendations": []
}
```

## Human-readable Output

In addition to the machine-readable JSON, the run emits a short human-readable summary listing the overall result, any failing items, and their suggested fixes. Example:

```
Audit result: FAIL

Failing items:
- c5 [output-schema-fidelity / major]: Output schema is missing field 'confidence'. Suggested fix: Restore the line 'confidence: number in [0, 1]'.
- c7 [no-hallucination / major]: New rule 'Reject high-risk inputs' was introduced by compression. Suggested fix: Remove the line and rerun the audit.

Warning items:
- c3 [ambiguity-reduction / minor]: Decision rule 'PASS if score >= 0.9' was tightened to '>= 0.85'. Review before shipping.
```

## Allowed Transformations

1. **Emitting a structured audit report** from a prompt target — this is the primary output of the pattern.
2. **Emitting a human-readable summary** alongside the JSON.
3. **Citing verbatim lines** from the target prompt as evidence.
4. **Naming new dimensions** in specialized audits, as long as the full dimension set is declared at the top of the run.

## Forbidden Transformations

1. **Mutating the target prompt during the audit.** The audit step must not write to the target.
2. **Issuing a PASS without evidence.** Every `PASS` item must have a non-empty `evidence` field.
3. **Ignoring hard constraints.** Any line in the target starting with imperative keywords (must, must not, never, always) must be explicitly checked.
4. **Silent upgrades from FAIL to WARN.** An item marked FAIL must stay FAIL; a reviewer must explicitly override.
5. **Using vague evidence.** "Looks fine" is never acceptable evidence.
6. **Rewriting prompt text as a side-effect of auditing.** If the audit reveals a defect, that defect is reported, not repaired, inside the audit pass.
7. **Combining audit with repair in a single pass.** Audit first; then — if needed — run a separate repair step with its own pattern (e.g., `incremental-fusion`).

## Examples

### Example 1 — PASS-on-all-dimensions.

Target: a well-structured classifier prompt.
Result: every checklist item is `PASS`. `failure_summary.overall = "PASS"`. The human summary reports "Audit result: PASS — no issues."

### Example 2 — FAIL-on-one-dimension.

Target: a compressed prompt in which a concrete decision rule (`PASS if score >= 0.9`) was replaced by a vague instruction (`Use your judgment about passing`).

Audit item on dimension `ambiguity-reduction`:

```json
{
  "id": "c3",
  "dimension": "ambiguity-reduction",
  "status": "FAIL",
  "evidence": "Original prompt contains 'PASS if score >= 0.9'. Compressed prompt contains 'Use your judgment about passing'. The concrete threshold was removed.",
  "issue": "A concrete decision rule has been replaced by a vague instruction, changing behavior.",
  "severity": "blocker",
  "suggested_fix": "Restore the line 'PASS if score >= 0.9' in the compressed prompt and rerun the audit."
}
```

Overall audit result: `FAIL`.

## Anti-examples

### Anti-example 1 — evidence-free PASS.

```json
{
  "id": "c1",
  "dimension": "completeness",
  "status": "PASS",
  "evidence": "The prompt looks complete to me."
}
```

**Violation:** The `evidence` field contains no verifiable content. No line is quoted, no schema property is checked. This is not a valid audit item.

### Anti-example 2 — silent mutation of target during audit.

An audit run that "fixes" a prompt defect while also reporting it.

**Violation:** The audit is read-only. Fixes require a separate step.

### Anti-example 3 — FAIL without a severity.

```json
{
  "id": "c7",
  "dimension": "no-hallucination",
  "status": "FAIL",
  "evidence": "...",
  "severity": null,
  "suggested_fix": null
}
```

**Violation:** A FAIL item must have a severity and a suggested_fix (even if the suggested_fix is to investigate).

## Self-check Checklist

Before shipping an audit result, verify every item on this meta-checklist:

- [ ] Audit target declared (kind + name + checksum).
- [ ] Dimensions used declared as a list.
- [ ] Every checklist item has a status in {PASS, WARN, FAIL}.
- [ ] Every checklist item has a non-empty evidence field.
- [ ] Every FAIL item has a severity from {blocker, major, minor, info}.
- [ ] Every FAIL item has a suggested_fix.
- [ ] Failure summary is produced (counts + ids).
- [ ] Hard-constraint lines were explicitly checked.
- [ ] Audit did not mutate the target.
- [ ] Machine-readable JSON produced; human-readable summary produced.
- [ ] Overall result is deterministic (identical on re-run).

## Test Contract

Every release of this pattern must satisfy the following tests. They are implemented in `tests/test_pattern_library_audit_checklist.py`:

1. **Doc-publishing test.** The pattern doc exists.
2. **README-registration test.** The pattern doc is registered in the library README by name.
3. **Default-enabled-false test.** The doc declares `Default enabled: false`.
4. **Audit-target test.** The doc documents the audit target.
5. **Audit-dimensions test.** The doc documents the default audit dimension set.
6. **Pass/warning/fail-semantics test.** The doc documents the three-valued conclusion semantics.
7. **Evidence-requirement test.** The doc requires evidence for every item.
8. **No-silent-pass test.** The doc explicitly forbids passing a dimension without evidence.
9. **Hard-constraint-strictness test.** The doc requires explicit checks for hard constraints.
10. **Audit-is-read-only test.** The doc forbids mutating the target during audit (except when entering repair mode, which is explicitly separate).
11. **Checklist-item-schema test.** The doc documents the checklist JSON fields: id, dimension, status, evidence, issue, severity, suggested_fix.
12. **Severity-levels test.** The doc documents blocker / major / minor / info.
13. **Failure-summary test.** The doc documents the failure summary structure.
14. **Repair-recommendation test.** The doc documents the repair recommendation field and its separation from audit execution.
15. **Machine-readable-output test.** The doc documents machine-readable JSON output.
16. **Human-readable-output test.** The doc documents human-readable summary output.
17. **Examples section present.**
18. **Anti-examples section present.**
19. **Self-check checklist section present.**
20. **Test-contract section present.**

## Migration Notes

- Do **not** wire this pattern into the default prompt-production pipeline. It is intended as an opt-in, on-demand tool.
- The audit is intentionally read-only. Keeping audit separate from repair keeps each step small, reviewable, and independently testable.
- The evidence-first rule is the single most important guardrail. If evidence cannot be produced for an item, the item should probably not be on the checklist.
- The three-dimension subset from `LLM_PRUNE_VALIDATION_PROMPT` — completeness, constraint-preservation, ambiguity-reduction — is a good default minimum set; the other dimensions extend it for richer audits.
- This pattern composes well with `compression-reverse-recovery`: run compression, run reverse-recovery if needed, then run `audit-checklist` on the result.
- Do **not** ship a prompt whose audit result has `overall == "FAIL"` without an explicit, reviewable override signed by a human.
- Do **not** enable by default: `default enabled: false` must remain true.
