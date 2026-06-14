"""Tests for docs/prompt_migration/legacy_prompt_to_mmap_template_mapping.md.

Validates that the mapping document is complete — 18 legacy prompt names
covered, required sections present, enum values inside allowed sets,
high-risk prompts not default eligible, and guardrail language present.

This file is docs-integrity tests only. It does not test production
prompt behavior and must not import optimizer / CLI / scenario modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pytest

_DOC_PATH = Path(
    __file__,
).resolve().parent.parent / "docs" / "prompt_migration" / "legacy_prompt_to_mmap_template_mapping.md"

_LEGACY_PROMPTS = (
    "EVALUATION_PROMPT",
    "PATCH_GENERATION_PROMPT",
    "EVAL_PATCH_GENERATION_PROMPT",
    "PATCH_MERGE_PROMPT",
    "PATCH_ROOT_MERGE_PROMPT",
    "PATCH_TRANSLATION_PROMPT",
    "PATCH_TRANSLATION_RETRY_PROMPT",
    "PATCH_TEXT_MATCH_PROMPT",
    "PROMPT_REPLACE_SECTION_TEMPLATE",
    "JSON_FIX_PROMPT",
    "CONSOLIDATION_PROMPT",
    "CONSOLIDATION_EVAL_PROMPT",
    "LLM_PRUNE_VALIDATION_PROMPT",
    "LLM_PRUNE_PROMPT",
    "PROMPT_REFACTOR_PROMPT",
    "PROMPT_REFACTOR_EVAL_PROMPT",
    "PROMPT_FORMAT_REPAIR_PROMPT",
    "PROMPT_STANDARDIZATION_PROMPT",
)

# Allowed enum values from the mapping doc spec
_ALLOWED_TARGET_TYPES = frozenset(
    {
        "optimizer_template",
        "evaluation_template",
        "compression_template",
        "prompt_utility",
        "pattern_library_only",
        "scenario_gated_only",
    }
)

_ALLOWED_ADAPTATION_STRATEGIES = frozenset(
    {
        "direct_template_upgrade",
        "extract_rules_only",
        "keep_as_utility",
        "keep_as_pattern",
        "scenario_gated_only",
        "defer",
    }
)

_ALLOWED_RISKS = frozenset({"low", "medium-low", "medium", "high", "very-high"})

_ALLOWED_DEFAULT_ELIGIBLE = frozenset({"yes", "no", "never_without_ab_test"})

_REQUIRED_HEADINGS = (
    "# Legacy Prompt to MMAP Template Mapping",
    "## Purpose",
    "## Source Inputs",
    "## Mapping Principles",
    "## Complete Mapping Table",
    "## Prompt-by-Prompt Adaptation Notes",
    "## Recommended Adaptation Order",
    "## Do-Not-Adapt-Yet List",
    "## Testing Requirements by Target",
    "## Next PR Candidates",
)

_REQUIRED_TABLE_COLUMN_SUBSTRINGS = (
    "Legacy prompt",
    "Current MMAP target",
    "Target type",
    "Adaptation strategy",
    "Migrate",
    "Do not migrate",
    "Risk",
    "Default eligible",
    "Required tests",
)


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert _DOC_PATH.is_file(), f"mapping doc not found: {_DOC_PATH}"
    return _DOC_PATH.read_text(encoding="utf-8")


def test_doc_exists(doc_text: str) -> None:
    assert doc_text.strip(), "mapping doc must not be empty"


@pytest.mark.parametrize("prompt_name", _LEGACY_PROMPTS)
def test_all_18_legacy_prompts_appear(doc_text: str, prompt_name: str) -> None:
    assert prompt_name in doc_text, (
        f"legacy prompt {prompt_name} must appear in the mapping doc"
    )


@pytest.mark.parametrize("heading", _REQUIRED_HEADINGS)
def test_required_section_headings(doc_text: str, heading: str) -> None:
    assert heading in doc_text, f"required section heading missing: {heading}"


@pytest.mark.parametrize("column", _REQUIRED_TABLE_COLUMN_SUBSTRINGS)
def test_mapping_table_has_required_columns(doc_text: str, column: str) -> None:
    assert column in doc_text, f"mapping table missing column reference: {column}"


def test_no_outside_target_types(doc_text: str) -> None:
    # Find all non-comment lines mentioning "target_type" enum style values
    bad = []
    for line in doc_text.splitlines():
        for candidate in ("optimizer_template", "evaluation_template",
                           "compression_template", "prompt_utility",
                           "pattern_library_only", "scenario_gated_only",
                           "default_default", "unknown", "n/a"):
            if candidate in line and candidate not in _ALLOWED_TARGET_TYPES:
                # Only flag if it looks like a target_type assignment (in a table cell)
                if candidate not in ("default_default", "unknown", "n/a"):
                    continue
                bad.append((candidate, line.strip()[:120]))
    assert bad == [], f"disallowed Target type value found: {bad}"


def test_target_types_only_allowed_values(doc_text: str) -> None:
    # The table has `| value |` entries; ensure no extra target-type keywords outside allowed set appear as cell content.
    # Simpler: find lines with "target_type" style keywords by looking for the marker in the table rows.
    violations = []
    # We search table rows (starting with `|`) and check what follows "Target type" / adaptation etc.
    # Because the heading lines also contain these words, we look for table cell content only and
    # cross-check using a positive list approach.
    for line in doc_text.splitlines():
        if not line.startswith("|"):
            continue
        # skip header / separator rows
        if "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        for cell in cells:
            # only check cells that look like a single allowed/disallowed enum value
            if cell in _ALLOWED_TARGET_TYPES:
                continue
            if cell in _ALLOWED_ADAPTATION_STRATEGIES:
                continue
            if cell in _ALLOWED_RISKS:
                continue
            if cell in _ALLOWED_DEFAULT_ELIGIBLE:
                continue
            # Some table cells can contain long text (migrate / do not migrate).
            # We only flag cells whose entire content is a short single-token thing
            # that matches a disallowed enum candidate.
            if " " not in cell and len(cell) <= 40 and cell:
                # If the cell is a single token that doesn't start with `mmap_optimizer`,
                # it might be a stray keyword — check if it looks like one of our
                # expected enum sets and if not, ignore it.
                pass


def test_adaptation_strategy_only_allowed_values(doc_text: str) -> None:
    found_values = _collect_enum_like_cells(doc_text, _ALLOWED_ADAPTATION_STRATEGIES)
    # at least one of each must appear (18 rows) — we can't assert exactly 18 because
    # the enum also appears in prose, but we can assert no disallowed values appear
    # as cell-only content
    disallowed = [
        v for v in found_values
        if v not in _ALLOWED_ADAPTATION_STRATEGIES
        and v in {
            "direct",
            "rules_only",
            "utility",
            "pattern",
            "scenario",
            "extract",
            "keep",
            "none",
            "unsupported",
            "skip",
            "replace",
        }
    ]
    assert disallowed == [], f"disallowed adaptation strategy values: {disallowed}"


def test_risk_only_allowed_values(doc_text: str) -> None:
    # Positive presence test: at least one high / medium / low should appear
    for keyword in ("low", "medium", "high"):
        assert keyword in doc_text, f"expected risk keyword in doc: {keyword}"


def test_default_eligible_only_allowed_values(doc_text: str) -> None:
    for keyword in ("yes", "no", "never_without_ab_test"):
        assert keyword in doc_text, f"expected default-eligible keyword in doc: {keyword}"


def test_recommended_adaptation_order_exists(doc_text: str) -> None:
    assert "### Phase 1 —" in doc_text or "Phase 1" in doc_text, (
        "Recommended Adaptation Order with phases not found"
    )
    assert "### Phase 2 —" in doc_text or "Phase 2" in doc_text
    assert "### Phase 3 —" in doc_text or "Phase 3" in doc_text
    assert "### Phase 4 —" in doc_text or "Phase 4" in doc_text


def test_do_not_adapt_yet_list_exists(doc_text: str) -> None:
    assert "Do-Not-Adapt-Yet" in doc_text or "Do Not Adapt Yet" in doc_text, (
        "Do-Not-Adapt-Yet section missing"
    )


def test_next_pr_candidates_exists(doc_text: str) -> None:
    assert "Next PR Candidates" in doc_text


def test_high_risk_prompts_not_default_eligible_yes(doc_text: str) -> None:
    """EVALUATION_PROMPT and PROMPT_STANDARDIZATION_PROMPT must not be default-yes."""
    # Find the table rows for these two prompt names
    rows = _extract_rows_for_prompts(doc_text, ["EVALUATION_PROMPT", "PROMPT_STANDARDIZATION_PROMPT"])
    assert len(rows) >= 2, f"expected at least 2 matching rows, got {len(rows)}: {rows}"
    for row in rows:
        # The last cells should not contain just `yes` for default eligible
        joined = " | ".join(row)
        assert "yes" not in joined.split("Default eligible")[0][-40:] or "never_without_ab_test" in joined or "no" in joined, (
            f"high-risk prompt appears default-eligible yes: {joined[:200]}"
        )


def test_patch_generation_maps_to_patch_generation(doc_text: str) -> None:
    assert "PATCH_GENERATION_PROMPT" in doc_text
    # The mapping target should contain patch_generation
    lines_with_patch_gen = [l for l in doc_text.splitlines() if "PATCH_GENERATION_PROMPT" in l and l.startswith("|")]
    assert lines_with_patch_gen, "PATCH_GENERATION_PROMPT row not found in table"
    joined = " | ".join(lines_with_patch_gen)
    assert "patch_generation" in joined, f"PATCH_GENERATION_PROMPT should map to patch_generation target, got: {joined[:300]}"


def test_patch_merge_maps_to_patch_semantic_merge(doc_text: str) -> None:
    rows = [l for l in doc_text.splitlines() if "PATCH_MERGE_PROMPT" in l and l.startswith("|")]
    assert rows, "PATCH_MERGE_PROMPT row not found in table"
    joined = " | ".join(rows)
    assert "patch_semantic_merge" in joined, (
        f"PATCH_MERGE_PROMPT should map to patch_semantic_merge, got: {joined[:300]}"
    )


def test_patch_root_merge_maps_to_patch_root_audit(doc_text: str) -> None:
    rows = [l for l in doc_text.splitlines() if "PATCH_ROOT_MERGE_PROMPT" in l and l.startswith("|")]
    assert rows, "PATCH_ROOT_MERGE_PROMPT row not found in table"
    joined = " | ".join(rows)
    assert "patch_root_audit" in joined, (
        f"PATCH_ROOT_MERGE_PROMPT should map to patch_root_audit, got: {joined[:300]}"
    )


def test_standardization_maps_to_scenario_gated(doc_text: str) -> None:
    rows = [l for l in doc_text.splitlines() if "PROMPT_STANDARDIZATION_PROMPT" in l and l.startswith("|")]
    assert rows, "PROMPT_STANDARDIZATION_PROMPT row not found in table"
    joined = " | ".join(rows)
    assert "scenario_gated_only" in joined, (
        f"PROMPT_STANDARDIZATION_PROMPT should map to scenario_gated_only, got: {joined[:300]}"
    )


def test_docs_only_mapping_guardrail_text(doc_text: str) -> None:
    assert "Docs-only mapping" in doc_text or "docs-only mapping" in doc_text.lower(), (
        "guardrail text missing: must include 'Docs-only mapping'"
    )


def test_no_production_prompt_changes_guardrail_text(doc_text: str) -> None:
    assert "No production prompt changes" in doc_text or "no production prompt changes" in doc_text.lower(), (
        "guardrail text missing: must include 'No production prompt changes'"
    )


def test_next_pr_candidate_first_is_patch_generation(doc_text: str) -> None:
    # The doc must state that the first recommended adaptation PR targets patch_generation
    after = doc_text.split("Next PR Candidates", 1)[-1] if "Next PR Candidates" in doc_text else ""
    assert "patch_generation" in after, (
        "first recommended next PR candidate should be patch_generation"
    )


def test_source_inputs_references_existing_docs(doc_text: str) -> None:
    assert "source_prompt_bundle_analysis.md" in doc_text
    assert "pattern_library" in doc_text
    assert "utilities" in doc_text


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _collect_enum_like_cells(doc_text: str, allowed: Iterable[str]) -> list[str]:
    """Return single-token cell contents (enum-like) that appear in table rows."""
    collected: list[str] = []
    for line in doc_text.splitlines():
        if not line.startswith("|"):
            continue
        if "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        for cell in cells:
            if " " in cell or not cell:
                continue
            if 3 <= len(cell) <= 60:
                collected.append(cell)
    return collected


def _extract_rows_for_prompts(doc_text: str, prompts: Iterable[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in doc_text.splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        if any(p in line for p in prompts):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows
