# Eval Patch Generation Legacy Strategy Adaptation

## Source Legacy Prompt

- **EVAL_PATCH_GENERATION_PROMPT** — generates patches for evaluation prompt improvements. Inputs: `{prompt_structure}`, `{current_prompt}`, `{file_name}`, `{status}`, `{reason}`, `{result_content}`, `{ground_truth}`, `{eval_blind_context}`. Output contract: same JSON patches + cited_sections format. Main capability: evaluation-logic-specific patch generation using a three-step workflow (Step 1 status check → Step 2 root cause → Step 3 operation selection) with ground-truth alignment framing.

## Current Target

- `mmap_optimizer/evaluation/prompt_optimizer.py::DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE` — the evaluation-patch-generation rule template that governs how `EvaluationPromptOptimizer.generate_patch_candidates()` transforms `EvaluationCase` mismatches into `PatchCandidate` objects.

The original `generate_patch_candidates` behavior is preserved:
- For each case where `case.expected != case.actual`, emit a single `PatchCandidate` with one `PatchOperation(op="add")` targeting `/evaluation_rules/{rule_hint}`
- Each candidate carries a new `EvaluationRule(rule_id, condition=reason, decision=expected, explanation=...)` payload
- `target_prompt_type` is fixed at `"evaluation"`
- The optimizer loop, patch applier, patch validator, behavior suite, and `EvaluationPromptOptimizer.optimize()` are unchanged

## Migrated Rules

1. **Evaluation-Grounded Patching** — generate patches only from the provided evaluation result, observed mismatch case, expected behavior, and current prompt. Do not invent failure modes not supported by evaluator evidence.
2. **Passing Case Returns Empty Patch List** — if `case.expected == case.actual`, return an empty patch list for that case. Do not generate improvement patches for passing cases.
3. **Failure-to-Rule Localization** — connect the failure reason to the most specific prompt rule, output-format requirement, decision condition, or missing constraint that should be changed. Use `case.rule_hint` to target `/evaluation_rules/{rule_hint}`.
4. **Minimal Patch Principle** — prefer the smallest localized patch that addresses the evaluator-supported failure. Avoid broad rewrites, global restatements, or unrelated style improvements.
5. **One Failure, One Patch Intent** — each patch addresses one evaluator-supported failure mode. Separate mismatches → separate `PatchCandidate` instances.
6. **No Evaluator Rewrite** — do not revise the evaluator decision, evaluator explanation, expected answer, or model output. Treat evaluation evidence as input evidence, not something to correct.
7. **No Speculative Patching** — do not patch for hypothetical future errors, general best practices, or unsupported assumptions. Patch only failures demonstrated in the provided evaluation context.
8. **Schema and Operation Preservation** — use only the current supported patch operations and fields: a single `PatchOperation(op="add")` targeting `/evaluation_rules/{rule_hint}` with an `EvaluationRule` payload. No new operations, fields, patch intents, or metadata.
9. **Output Contract Strictness** — return exactly the current required patch output format: `PatchCandidate(patch_id, title, operations, rationale, source_case_ids, target_prompt_type)`. No Markdown, no extra commentary, no undefined fields.
10. **Confidence / Ambiguity Handling** — if evaluator evidence is insufficient to identify a safe prompt change, return no patch for that failure. Do not guess.

## Rules Not Migrated

- **No patch schema changes** — `PatchCandidate`, `PatchOperation`, `EvaluationRule` shapes preserved.
- **No evaluator output schema changes** — `output_schema` / `output_format` / `prompt_type` in `PromptIR` preserved.
- **No new operations** — only `op="add"` for new rules.
- **No new fields** — existing `PatchCandidate` field set preserved.
- **No new patch intents** — patch purpose remains "add evaluation rule for mismatched case."
- **No optimizer loop / orchestration / CLI / scenario changes** — pure template content only.
- **No patch applier changes** — `PatchApplier.apply()` is not touched.
- **No evaluator runtime / parser changes** — behavior suite is not modified.
- **No unrelated template changes** — `patch_generation`, `patch_semantic_merge`, `patch_root_audit`, `patch_translation`, `patch_translation_retry`, `patch_text_match`, `json_fix`, evaluator prompt template are not modified.
- **No direct copy of legacy prompt wholesale** — strategy rules adapted to the current codebase terminology.

## Contract Preservation

| Aspect | Before | After |
| --- | --- | --- |
| `PatchCandidate` fields | `patch_id, title, operations, rationale, source_case_ids, target_prompt_type` | unchanged |
| `PatchOperation.op` | `"add"` only in this path | unchanged |
| `PatchOperation.path` | `/evaluation_rules/{rule_hint}` | unchanged |
| `PatchOperation.value` | `EvaluationRule` | unchanged |
| `EvaluationRule` fields | `rule_id, condition, decision, explanation` | unchanged |
| `target_prompt_type` | `"evaluation"` | unchanged |
| `PromptIR.output_schema` | frozen at `{"decision": "string", "reason": "string"}` | unchanged (enforced by validator) |
| `PromptIR.output_format` | frozen at `"json"` | unchanged (enforced by validator) |
| Optimizer `optimize()` contract | `(prompt_version, mismatch_cases) -> (next_version, report)` | unchanged |

## Risk

- **Risk level**: medium
- Default behavior only modified through template content / rule text
- The stricter evaluation-grounded discipline reduces speculative patches; verify on scenario suites before broad adoption
- **Required follow-up**: measure patch-acceptance rate on existing scenarios; compare with pre-adaptation baseline

## Tests

`tests/test_eval_patch_generation_prompt_template.py` covers:

- **Existence** — `DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE`, `DEFAULT_EVAL_PATCH_GENERATION_OUTPUT_CONTRACT`, and `get_default_eval_patch_generation_template()` all exist and are non-empty.
- **Contract preservation** — `PatchCandidate` fields present in template text; only `op="add"` listed; `target_prompt_type="evaluation"` fixed; no new required fields; no new operations introduced.
- **Migrated rule presence** — all 10 legacy rules confirmed by phrase-matching in template.
- **Guardrails** — no optimizer-loop modifications; no schema changes; no unsupported ops; no Markdown/fences in output contract.
- **Other-template isolation** — no `patch_semantic_merge`, `patch_root_audit`, `patch_translation`, `json_fix`, `compression`, or `four-strategy` keywords bleed in.
- **Integration** — module import still works; `EvaluationPromptOptimizer.generate_patch_candidates` still produces single-`PatchCandidate` with correct target/op/path; passing cases (`expected == actual`) still produce zero candidates (Rule 2).
