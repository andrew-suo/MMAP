# Prompt Pattern Library

Location: `docs/prompt_migration/pattern_library/`

This directory collects the low-risk pattern library derived from the legacy
prompt bundle analyzed in `source_prompt_bundle_analysis.md` (PR #47). Each
pattern documents one well-defined, narrowly-scoped prompt transformation with
a written contract and a matching test file.

**Current status.** This library is documentation-and-tests only. No pattern is
wired into the default `prompts/raw/` pipeline, optimizer loop, or CLI
behavior. Integrating a pattern into a real prompt path is a separate,
reviewable decision — never automatic.

**Risk policy.** Patterns are added in roughly the order
`low → medium → high`. See `source_prompt_bundle_analysis.md` for the full
matrix. The current release ships patterns classified as **Low**,
**Medium-low**, and **Medium** risk.

## Index

| # | Pattern name | Source legacy prompts | Risk | Status | Default enabled | Explicit utility |
|---|---|---|---|---|---|---|
| 1 | `numbering-only-refactor` | `PROMPT_REFACTOR_PROMPT`, `PROMPT_REFACTOR_EVAL_PROMPT` | **Low** | `shipped` | **false** | `mmap_optimizer.prompt.numbering_refactor` |
| 2 | `json-repair-position-valid` | `JSON_FIX_PROMPT`, `PATCH_TRANSLATION_PROMPT` (output clause), `PATCH_TRANSLATION_RETRY_PROMPT` | **Low** | `shipped` | **false** | `mmap_optimizer.prompt.json_repair` |
| 3 | `immutable-payload` | `PATCH_TRANSLATION_PROMPT`, `PATCH_TRANSLATION_RETRY_PROMPT`, `PATCH_TEXT_MATCH_PROMPT` | **Medium-low** | `shipped` | **false** | `mmap_optimizer.prompt.immutable_payload` |
| 4 | `incremental-fusion` | `PROMPT_REPLACE_SECTION_TEMPLATE`, `PATCH_GENERATION_PROMPT`, `PATCH_ROOT_MERGE_PROMPT` | **Medium** | `shipped` | **false** | *(planned)* |
| 5 | `compression-reverse-recovery` | `CONSOLIDATION_PROMPT`, `CONSOLIDATION_EVAL_PROMPT`, `LLM_PRUNE_PROMPT`, `LLM_PRUNE_VALIDATION_PROMPT` | **Medium** | `shipped` | **false** | *(planned)* |
| 6 | `audit-checklist` | `LLM_PRUNE_VALIDATION_PROMPT`, `PATCH_TRANSLATION_RETRY_PROMPT`, `CONSOLIDATION_PROMPT`, evaluation-family prompts | **Medium-low** | `shipped` | **false** | `mmap_optimizer.prompt.audit_checklist` |

## Recommended next step

Pick one narrow next step:

- Wire one of the lower-risk patterns (e.g., `numbering-only-refactor`,
  `immutable-payload`, or `audit-checklist`) as a **scenario-gated** /
  explicitly-named utility function (never automatic in the default path).
- Or add the fourth batch: `structured-output-schema` + `evaluation-scoring-calibration`
  (from `PROMPT_STANDARDIZATION_PROMPT` and the evaluation-family prompts).

Do **not** ship the following in the default pipeline until a scenario-gating
mechanism exists:

- 7-section standardization pattern (`PROMPT_STANDARDIZATION_PROMPT`).
- 3-state evaluation pattern (`EVALUATION_PROMPT` — which replaces the
  current binary eval style).

## Explicit utility modules

Starting from PR #51 and the current PR, selected patterns ship with a
corresponding **explicit Python utility module** in `mmap_optimizer.prompt.*`
that callers can invoke manually (never automatically). Every utility:

- is exposed under `mmap_optimizer.prompt.<name>`;
- ships with a `tests/test_prompt_<name>_utility.py` test file;
- ships with a `docs/prompt_migration/utilities/<name>_utility.md` doc;
- ships with **default enabled: false**;
- has **zero dependency** on `mmap_optimizer.model.*`,
  `mmap_optimizer.orchestration.*`, or any live prompt path.

Currently-shipped explicit utilities:

| Pattern | Module | Invocation |
|---|---|---|
| `numbering-only-refactor` | `mmap_optimizer.prompt.numbering_refactor` | `refactor_prompt_numbering_only(text) -> str`, `detect_numbering_issues(text) -> list[NumberingIssue]` |
| `json-repair-position-valid` | `mmap_optimizer.prompt.json_repair` | `repair_json_output(text) -> JsonRepairResult`, `parse_json_strict(text) -> Any`, `strip_json_code_fence(text) -> str`, `extract_position_valid_json_candidate(text) -> str`, `ensure_position_valid_json(text) -> str` |
| `immutable-payload` | `mmap_optimizer.prompt.immutable_payload` | `validate_immutable_payload(original, rewritten) -> ImmutablePayloadValidationResult`, `stable_payload_hash(text) -> str`, `extract_placeholders(text) -> tuple[str, ...]` |
| `audit-checklist` | `mmap_optimizer.prompt.audit_checklist` | `build_audit_checklist_report(*, target_id, items, metadata) -> AuditChecklistReport`, `validate_audit_checklist_report(report) -> tuple[str, ...]`, `render_audit_checklist_summary(report) -> str`, `audit_checklist_to_json(report) -> str`, `audit_checklist_from_dict(data) -> AuditChecklistReport` |

## Guardrails (apply to every pattern in this library)

1. **No production behavior change by default.** Every pattern ships with
   `default enabled: false`.
2. **No optimizer loop change.** No pattern reads from or writes to the
   orchestration loop.
3. **No scenario change.** No pattern mutates `scenarios/` by default.
4. **No CLI change.** No pattern adds or removes CLI flags or commands.
5. **No raw-prompt replacement.** No pattern is allowed to overwrite files
   under `prompts/raw/`. A pattern that needs to produce a prompt variant
   must write to a separate, explicitly-named file.
6. **No LLM call.** The test contract for every pattern must be verifiable
   offline, without invoking a language model.
7. **Deterministic.** Same input → same output, always.
8. **Documented.** Every pattern ships with a Markdown file in this directory
   and a matching test file in `tests/`.
