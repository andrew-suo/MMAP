# Evaluation Legacy Strategy Adaptation

## Source Legacy Prompt

- **EVALUATION_PROMPT** — defines the evaluation discipline for judging model outputs against expected answers. Includes: eval-blind context discipline, passing case protection, failure localization, distinguishing semantic vs formatting failures, evidence-grounded judgement, no patch generation during evaluation, minimal actionable failure reason, output contract strictness, and ambiguity handling.

## Current Target

- `mmap_optimizer/prompts.py::DEFAULT_EVALUATION_PROMPT_SYSTEM` — the `system` field of the evaluation `PromptIR`. Rendered via `PromptIR.render()` which produces:
  - `system` instructions
  - `Evaluation rules:` section (from `evaluation_rules` tuple)
  - `Output format:` + `Output schema:` footer lines

The evaluation prompt IR is consumed by `mmap_optimizer/evaluation/prompt_optimizer.py` for evaluation-specific prompt optimization, and by `mmap_optimizer/evaluation/evaluator.py` (via `EvaluationRecord` / `EvaluationStatus` and label normalization) for evaluation of actual model outputs.

The original default `system` content was minimal: `"Evaluate the answer and return only the frozen JSON schema."` — no legacy evaluation discipline was encoded.

## Migrated Rules

1. **Eval-Blind Context Discipline** — Evaluate only from the provided prompt, input, expected answer / ground truth, and model output. Do not use outside knowledge or infer unstated business rules.
2. **Passing Case Protection** — If the model output satisfies the expected behavior, mark it as correct / pass using the existing output vocabulary. Do not invent improvement suggestions for passing cases.
3. **Failure Localization** — When the output is wrong, identify the most specific failure reason and locate the violated prompt rule, output-format requirement, or decision condition.
4. **Separate Task Failure from Formatting Failure** — Distinguish semantic / task-decision failures from output-format / schema failures. Report both if present; never collapse into a vague generic error.
5. **Evidence-Grounded Judgement** — Every failure explanation must be grounded in observable evidence from the model output, expected answer / ground truth, or current prompt text.
6. **No Patch Generation During Evaluation** — Evaluation diagnoses correctness and failure reasons only. Never generate patch objects, rewrite prompt sections, or propose patch operations.
7. **Minimal Actionable Failure Reason** — Prefer concise, actionable failure reason that can guide downstream patch generation. Avoid broad statements like "be more careful."
8. **Output Contract Strictness** — Return exactly the current required evaluation output format. No Markdown, explanations outside JSON, fences, or extra commentary.
9. **Ambiguity Handling** — If correctness cannot be determined, use the existing uncertainty / invalid / inconclusive mechanism if one exists. Otherwise, choose the closest existing status without inventing a new status.

## Rules Not Migrated

- **No output schema changes** — still `{"decision": "string", "reason": "string"}`.
- **No new fields** — no new required or optional output fields.
- **No new operations** — evaluation is still about decision + reason, not content generation.
- **No new patch intents** — evaluator still does not author patches.
- **No semantic rewriting of model output** — still a pure judge, not an editor.
- **No optimizer loop / CLI / scenario changes** — pure prompt content only.
- **No patch-template behavior changes** — patch_generation, patch_text_match, etc. are not touched.

## Contract Preservation

| Aspect | Before | After |
| --- | --- | --- |
| `prompt_type` | `"evaluation"` | unchanged |
| `output_format` | `"json"` | unchanged |
| `output_schema` | `{"decision": "string", "reason": "string"}` | unchanged |
| `evaluation_rules` element shape | `EvaluationRule(rule_id, condition, decision, explanation="")` | unchanged |
| `PromptIR.render()` output shape | `system + "Evaluation rules:\n..." + "Output format: ..." + "Output schema: ..."` | unchanged |
| Decision vocabulary | Determined by `EvaluationRule.decision` / `EvaluationStatus` (e.g. correct, wrong, schema_error, parse_error) | unchanged |
| Label normalization | `合格/正常 → OK, 不合格/异常 → NG, 无法确认/不确定 → UNCERTAIN` | unchanged |

## Risk

- **Risk level**: medium
- Default behavior is only modified through prompt/template content; no schema, no runtime, no optimizer loop.
- The evaluation discipline is stricter than the previous implicit "free judgement" default, so a few edge cases may flip from accept to reject if the judge previously ignored evidence.
- **Required follow-up**: measure evaluation-label agreement rate before/after on the existing scenario suite; compare distribution of `overall_status` values.

## Tests

`tests/test_evaluation_prompt_template.py` covers:

- **Existence** — `DEFAULT_EVALUATION_PROMPT_SYSTEM`, `DEFAULT_EVALUATION_OUTPUT_SCHEMA`, and `make_default_evaluation_prompt_ir()` all exist and produce well-formed `PromptIR` with `prompt_type="evaluation"`, `output_format="json"`, non-empty `render()`.
- **Contract preservation** — `output_schema` is exactly `{"decision": "string", "reason": "string"}`; no new required fields; adding new `evaluation_rules` preserves schema and output format.
- **Migrated rule presence** — all nine legacy rules confirmed by phrase-matching in the rendered prompt text.
- **Guardrails** — template must not instruct optimizer loop modification; must not invent new status labels; must not introduce new output fields; must not mention patch operations in its pure system text.
- **Round-trip** — `PromptVersion` can wrap the default IR and be `bump`-ed to a new version while preserving the output schema and format.
