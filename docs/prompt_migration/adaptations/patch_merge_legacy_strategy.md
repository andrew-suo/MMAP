# Patch Merge Legacy Strategy Adaptation

This document records the adaptation of the legacy `PATCH_MERGE_PROMPT`
merge-strategy rules into the current MMAP `patch_semantic_merge`
optimizer template. This is the second real prompt/template adaptation
(preceded by `patch_generation`).

## Source Legacy Prompt

- **Name (historical)**: `PATCH_MERGE_PROMPT`
- **Purpose**: given a prompt structure and a set of candidate patch
  objects, merge overlapping/redundant patches into a compact, conflict-free
  patch list without inventing new rules or operations.
- **Storage**: legacy archive only — not directly imported into this repo.

## Current Target

- **Module**: `mmap_optimizer/templates/optimizer_prompts.py`
- **Template constant**: `PATCH_SEMANTIC_MERGE_TEMPLATE`
- **Registry key**: `patch_semantic_merge`
- **Version**: `1.1` (unchanged)
- **Input variables** (unchanged): `prompt_structure`, `patches_json`
- **Output contract** (unchanged): JSON array of patch objects; original
  patch array as fallback.

## Migrated Rules

The following rules from `PATCH_MERGE_PROMPT` have been adapted into
`PATCH_SEMANTIC_MERGE_TEMPLATE`:

1. **Three-dimensional merge framework**
   - Dimension 1 — Structure Isolation: group patches by target section /
     section id / nearby location.
   - Dimension 2 — Logic Deduplication: keep the clearest, most specific
     version of patches expressing the same intent.
   - Dimension 3 — Technical Constraints: preserve JSON schema, supported
     operations, patch count validity, locator applicability, and
     line-level non-overlap.

2. **Group-by-section discipline**
   - First group by target section or section identifier.
   - Within each group, deduplicate and resolve conflicts.
   - Across groups, preserve independent patches unless clear cross-section
     conflict.

3. **Unique valid patch preservation**
   - If a patch is the only valid patch addressing a distinct failure
     pattern and it does not conflict, preserve it even if no other patch
     suggests the same change.

4. **Popularity bias as soft signal**
   - Recurring patch intent across multiple candidates is a soft priority
     signal, not a hard deletion rule. Used to prefer among equivalent
     fixes; does not drop unique valid patches.

5. **Conflict resolution by reasoning sufficiency**
   - When two patches conflict, prefer the one with clearer evidence,
     narrower scope, better alignment with the failure reason, and fewer
     side effects.

6. **Line-level / locator non-overlap**
   - Do not emit merged patches requiring overlapping edits to the same
     exact text span unless they have been consolidated into one valid
     patch.

7. **Compact merged patch list without fixed compression ratio**
   - Prefer a compact merged patch list, but do not force a fixed
     compression ratio (no hard 1/3 target).

8. **Supported operations only**
   - Use only operations supported by the current patch schema. Do not
     invent new operation names, new fields, or new patch object shapes.

9. **No cross-section semantic drift**
   - Do not merge unrelated section-local patches into a broad global
     rewrite. Merging must preserve original intent and target locality.

## Rules Not Migrated

The following items from the legacy prompt were intentionally left out:

- **No patch schema changes**: output contract remains a plain JSON array
  of patch objects (same shape as before).
- **No new required fields**: no extra top-level or per-patch fields added.
- **No new operations**: append_to_section through delete_section set is
  preserved without additions.
- **No fixed 1/3 compression ratio**: the legacy 1/3 target is NOT enforced
  — compaction is guidance only.
- **No hard popularity deletion**: popularity bias remains a soft signal,
  never a hard delete rule.
- **No optimizer loop changes**: optimizer loop / orchestrator code is
  untouched.
- **No patch_generation changes**: the patch_generation template is left
  exactly as it was after PR #63.
- **No root_audit changes**: root audit template is unchanged.
- **No direct wholesale copy of legacy prompt**: rules are rephrased to
  fit the current mixed Chinese + English template style.

## Contract Preservation

- **Input placeholders**: `{prompt_structure}` and `{patches_json}` only.
- **Output shape**: JSON array of patch objects.
- **Fallback**: original patch array unchanged.
- **Registry version**: `1.1` unchanged.
- **Supported operations**: the existing set is preserved without
  additions.
- **No new fields**: no extra keys required or allowed in output patches.

## Risk

- **Risk level**: **medium**
- **Rationale**: this is pure template content change. However, merging
  strategy can change the volume, diversity, and specificity of patches
  that reach downstream stages. The real impact must be measured in A/B
  eval.
- **Default behavior**: changed only through template content; no
  schema/runtime changes.
- **Required follow-up**: A/B eval in real optimization loop before
  broader adoption.

## Tests

Contract tests for the adapted template:

- `tests/test_optimizer_prompt_patch_merge_template.py`

These tests verify:

- Template existence and render with required placeholders.
- Output contract shape preserved (JSON array; fallback to original).
- All 9+ migrated rules present in rendered template.
- Guardrails: no references to optimizer loop, no schema changes, no
  fixed compression ratio, popularity bias treated as soft signal only.
- Other templates (patch_generation, patch_root_audit,
  patch_translation, patch_translation_retry, patch_text_match,
  json_fix) not polluted by this adaptation.

Run with:

```
python -m pytest tests/test_optimizer_prompt_patch_merge_template.py -q
```
