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
matrix. The current release only ships patterns classified as **Low** risk.

## Index

| # | Pattern name | Source legacy prompts | Risk | Status | Default enabled |
|---|---|---|---|---|---|
| 1 | `numbering-only-refactor` | `PROMPT_REFACTOR_PROMPT`, `PROMPT_REFACTOR_EVAL_PROMPT` | **Low** | `shipped` | **false** |
| 2 | `json-repair-position-valid` | `JSON_FIX_PROMPT`, `PATCH_TRANSLATION_PROMPT` (output clause), `PATCH_TRANSLATION_RETRY_PROMPT` | **Low** | `shipped` | **false** |

## Recommended next step

Add the following patterns, each in its own PR:

- **Immutable payload** (derived from `PATCH_TRANSLATION_PROMPT`'s payload
  protection clause) — medium-low risk.
- **Incremental fusion** (derived from `PROMPT_REPLACE_SECTION_TEMPLATE`) —
  medium risk, requires a clear "old content + new rules" merge contract.

Do **not** ship the following in the default pipeline until a scenario-gating
mechanism exists:

- 7-section standardization pattern (`PROMPT_STANDARDIZATION_PROMPT`).
- 3-state evaluation pattern (`EVALUATION_PROMPT` — which replaces the
  current binary eval style).

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
