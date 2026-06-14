# Patch Root Audit Legacy Strategy Adaptation

This document records the adaptation of the legacy `PATCH_ROOT_MERGE_PROMPT`
four-dimension cross-section audit framework into the current MMAP
`patch_root_audit` optimizer template. This is the third real
prompt/template adaptation PR.

Preceding adaptations:
- `PATCH_GENERATION_PROMPT` → `patch_generation`
- `PATCH_MERGE_PROMPT` → `patch_semantic_merge`

## Source Legacy Prompt

- **Name (historical)**: `PATCH_ROOT_MERGE_PROMPT`
- **Purpose**: Given a prompt structure and a set of candidate patch
  objects, perform a final cross-section audit to detect conflicts before
  patches are applied. The goal is conflict detection, not new patch
  generation.
- **Storage**: legacy archive only — not directly imported into this repo.

## Current Target

- **Module**: `mmap_optimizer/templates/optimizer_prompts.py`
- **Template constant**: `PATCH_ROOT_AUDIT_TEMPLATE`
- **Registry key**: `patch_root_audit`
- **Version**: `1.1` (unchanged)
- **Input variables** (unchanged): `prompt_structure`, `patches_json`
- **Output contract** (unchanged): JSON array of patch objects; original
  patch array as fallback; empty `[]` in error cases.

## Migrated Rules

The following cross-section audit rules from `PATCH_ROOT_MERGE_PROMPT`
have been adapted into `PATCH_ROOT_AUDIT_TEMPLATE`:

1. **Cross-section audit framework — 4 dimensions**
   - **Audit Dimension 1 — Rules ↔ Output Format consistency**: check
     whether patches change rules, labels, fields, JSON structure, or
     decision vocabulary in a way that conflicts with the Output Format
     section.
   - **Audit Dimension 2 — Workflow ↔ Rules consistency**: check whether
     patches add/change workflow steps without corresponding rule support,
     or add rules that the workflow never applies.
   - **Audit Dimension 3 — Redundancy and duplication**: detect duplicate
     or near-duplicate patches across sections; prefer consolidation over
     deleting the only valid patch for a failure mode.
   - **Audit Dimension 4 — Orphan protection**: detect patches that
     introduce concepts, labels, fields, examples, or constraints not
     referenced by any related workflow/rule/output section.

2. **Modify-first, never-delete-by-default**
   - When a conflict is found, prefer a minimal modification that
     preserves the useful part of the patch. Do not delete a patch unless
     it is truly redundant, unsupported, or impossible to reconcile with
     the prompt contract.

3. **Never add new patches in root audit**
   - Do not create brand-new patches during root audit. Only keep,
     remove, or minimally adjust patches already present in the input,
     if the current output contract supports adjustment. Return only
     audited versions of input patches. Do not invent new patch intents.

4. **Preserve unique valid patches**
   - If a patch is the only non-conflicting patch addressing a distinct
     failure mode, preserve it. Do not remove unique valid patches merely
     because they are low-frequency or not duplicated elsewhere.

5. **Common cross-section conflict examples**
   - Rule says output one label, Output Format defines another label set.
   - Workflow adds a step whose result is never used.
   - Patch adds a JSON field but Output Format does not define it.
   - Patch adds an exception but no decision rule references it.

6. **Schema and operation preservation**
   - Use only the current patch schema and supported operations. Do not
     invent new operation names, fields, decision objects, or patch shapes
     during root audit.

7. **No broad global rewrite**
   - Do not convert several localized patches into a broad global rewrite.
     Root audit should reduce conflicts while preserving section locality
     and original patch intent.

8. **Output-format sensitivity**
   - Output Format changes are high-impact. Any patch that modifies
     output structure, label vocabulary, required fields, or JSON shape
     must be checked against all related rules and workflow steps.

9. **No hallucinated requirements**
   - Only audit against the provided prompt structure, current prompt,
     and input patches. Do not introduce requirements from outside the
     provided context.

## Rules Not Migrated

The following items were intentionally left out:

- **No patch schema changes**: output contract remains a plain JSON
  array of patch objects (same shape as before).
- **No new required fields**: no extra top-level or per-patch fields
  added.
- **No new operations**: the supported operation set is preserved without
  additions.
- **No new patch intents**: root audit must not generate brand-new
  patches.
- **Root audit does not become patch generation**: the template makes
  explicit the audit-layer boundary.
- **No optimizer loop behavior changes**: orchestrator logic is untouched.
- **No patch_generation / patch_semantic_merge / translation template
  changes**: these templates remain exactly as they were after their
  respective adaptations (or original form for translation).
- **No direct wholesale copy of legacy prompt**: rules are rephrased to
  fit the current mixed Chinese + English template style.

## Contract Preservation

- **Input placeholders**: `{prompt_structure}` and `{patches_json}` only.
- **Output shape**: JSON array of patch objects; original patch array
  and `[]` as fallbacks.
- **Registry version**: `1.1` unchanged.
- **Supported operations**: the existing set is preserved.
- **No new fields**: no extra keys required or allowed.

## Risk

- **Risk level**: **medium-low**
- **Rationale**: pure template content change with strong guardrails
  against new-patch generation. However, audit behavior changes could
  alter which patches pass through and which are rejected; real-loop
  A/B eval is required before broad adoption.
- **Default behavior**: changed only through template content; no
  schema/runtime changes.
- **Required follow-up**: A/B eval in real optimization loop before
  broader adoption.

## Tests

Contract tests for the adapted template:

- `tests/test_optimizer_prompt_patch_root_audit_template.py`

These tests verify:

- Template existence and render with required placeholders.
- Output contract shape preserved (JSON array; fallback intact).
- All 9+ migrated rules present in rendered template text.
- Guardrails: no references to optimizer loop, no schema changes, no
  new operations, no patch_generation/merge references, no new required
  fields.
- Other templates (patch_generation, patch_semantic_merge,
  patch_translation, patch_translation_retry, patch_text_match,
  json_fix) not polluted by this adaptation.

Run with:

```
python -m pytest tests/test_optimizer_prompt_patch_root_audit_template.py -q
```
