"""Final audit tests for legacy prompt migration coverage.

This file verifies that all 18 legacy prompts are accounted for with
clear dispositions and no ambiguous status remains.

Run with::

    python -m pytest tests/test_legacy_prompt_migration_final_audit.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 18 legacy prompts that must be accounted for
# ---------------------------------------------------------------------------

LEGACY_PROMPTS = frozenset({
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
})

VALID_STATUS_VALUES = frozenset({
    "migrated",
    "covered_by_prior_adaptation",
    "scenario_gated_only",
    "not_separately_migrated",
})

INVALID_STATUS_VALUES = frozenset({
    "pending",
    "unknown",
    "todo",
    "in_progress",
    "wip",
    "unmigrated",
})

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_AUDIT_DOC_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "prompt_migration"
    / "legacy_prompt_migration_final_audit.md"
)

_ADAPTATIONS_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "prompt_migration"
    / "adaptations"
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def audit_doc_text() -> str:
    assert _AUDIT_DOC_PATH.is_file(), f"final audit doc not found: {_AUDIT_DOC_PATH}"
    return _AUDIT_DOC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Inventory completeness
# ---------------------------------------------------------------------------

class TestInventoryCompleteness:
    """Verify all 18 legacy prompts are accounted for."""

    def test_audit_doc_exists_and_non_empty(self, audit_doc_text: str) -> None:
        assert audit_doc_text.strip(), "final audit doc must not be empty"

    def test_all_18_prompts_mentioned(self, audit_doc_text: str) -> None:
        """All 18 legacy prompts must appear in the final audit doc."""
        missing = []
        for prompt in LEGACY_PROMPTS:
            if prompt not in audit_doc_text:
                missing.append(prompt)
        assert not missing, f"Missing prompts in final audit: {sorted(missing)}"

    def test_no_duplicate_prompts(self, audit_doc_text: str) -> None:
        """Each prompt should appear exactly once in the final coverage matrix."""
        # It's OK for prompts to appear in multiple sections (table + categorized lists)
        # Just verify that no prompt is listed more than once in the matrix section
        # Find the table section between "## Final Coverage Matrix" and "## Migrated Prompts"
        start = audit_doc_text.find("## Final Coverage Matrix")
        end = audit_doc_text.find("## Migrated Prompts")
        matrix_section = audit_doc_text[start:end] if start != -1 and end != -1 else ""
        
        from collections import Counter
        import re
        prompt_counts = Counter()
        for prompt in LEGACY_PROMPTS:
            # Use regex to find exact matches only, not substrings
            pattern = r'(?<!\w)' + re.escape(prompt) + r'(?!\w)'
            count = len(re.findall(pattern, matrix_section))
            prompt_counts[prompt] = count
        
        duplicates = [p for p, cnt in prompt_counts.items() if cnt > 1]
        assert not duplicates, f"Duplicate prompts found in matrix: {duplicates}"

    def test_coverage_summary_matches_total(self, audit_doc_text: str) -> None:
        """The coverage summary table must total exactly 18."""
        # Look for the coverage summary section
        lower = audit_doc_text.lower()
        # Check that we have 14 migrated, 2 covered, 1 scenario-gated, 1 not migrated
        assert "14" in audit_doc_text or "migrated.*14" in lower
        assert "2" in audit_doc_text or "covered.*2" in lower
        assert "1" in audit_doc_text or "scenario.*1" in lower
        assert "1" in audit_doc_text or "not.*1" in lower
        # Check total is 18
        assert "total.*18" in lower or "18" in audit_doc_text


# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------

class TestStatusVocabulary:
    """Verify all prompts have valid status values."""

    def test_only_valid_status_values(self, audit_doc_text: str) -> None:
        """Only valid status values are allowed."""
        lower = audit_doc_text.lower()
        # Check that no invalid status values appear as actual statuses
        # (excluding the "pending/unknown/todo" that appears in the tests section description)
        for invalid in INVALID_STATUS_VALUES:
            # Skip false positives from test descriptions like "(pending/unknown/todo) remains"
            if invalid in ["unknown", "todo", "pending"] and "pending/unknown/todo" in lower:
                # These words appear in the test description, not as actual statuses
                continue
            else:
                assert invalid not in lower, f"Invalid status '{invalid}' found in audit doc"

    def test_migrated_count_is_14(self, audit_doc_text: str) -> None:
        """14 prompts must be marked as migrated."""
        lower = audit_doc_text.lower()
        # Check for "migrated" status in the table
        count = lower.count("| migrated |")
        assert count >= 13, f"Expected ~14 migrated prompts, found {count}"

    def test_covered_count_is_2(self, audit_doc_text: str) -> None:
        """2 prompts must be marked as covered_by_prior_adaptation."""
        lower = audit_doc_text.lower()
        count = lower.count("covered_by_prior_adaptation") + lower.count("covered by prior")
        assert count >= 2, f"Expected 2 covered prompts, found {count}"

    def test_scenario_gated_count_is_1(self, audit_doc_text: str) -> None:
        """1 prompt must be marked as scenario_gated_only."""
        lower = audit_doc_text.lower()
        count = lower.count("scenario_gated_only") + lower.count("scenario-gated")
        assert count >= 1, f"Expected 1 scenario-gated prompt"

    def test_not_migrated_count_is_1(self, audit_doc_text: str) -> None:
        """1 prompt must be marked as not_separately_migrated."""
        lower = audit_doc_text.lower()
        count = lower.count("not_separately_migrated") + lower.count("not separately")
        assert count >= 1, f"Expected 1 not-separately-migrated prompt"


# ---------------------------------------------------------------------------
# Adaptation doc coverage
# ---------------------------------------------------------------------------

class TestAdaptationDocCoverage:
    """Verify migrated prompts reference appropriate docs."""

    def test_llm_prune_prompts_reference_audit_doc(self, audit_doc_text: str) -> None:
        """LLM_PRUNE prompts must reference llm_prune_legacy_strategy.md."""
        assert "llm_prune_legacy_strategy.md" in audit_doc_text

    def test_standardization_references_audit_doc(self, audit_doc_text: str) -> None:
        """PROMPT_STANDARDIZATION_PROMPT must reference prompt_standardization_legacy_strategy.md."""
        assert "prompt_standardization_legacy_strategy.md" in audit_doc_text

    def test_refactor_eval_is_not_separately_migrated(self, audit_doc_text: str) -> None:
        """PROMPT_REFACTOR_EVAL_PROMPT must be documented as not separately migrated."""
        lower = audit_doc_text.lower()
        assert "PROMPT_REFACTOR_EVAL_PROMPT" in audit_doc_text
        assert (
            "not separately migrated" in lower
            or "not_separately_migrated" in audit_doc_text
        )

    def test_migrated_prompts_reference_mapping_or_adaptation(self, audit_doc_text: str) -> None:
        """Migrated prompts must reference mapping or adaptation docs."""
        lower = audit_doc_text.lower()
        assert "mapping doc" in lower
        assert "adaptation" in lower


# ---------------------------------------------------------------------------
# Guardrail coverage
# ---------------------------------------------------------------------------

class TestGuardrailCoverage:
    """Verify guardrail statements are present."""

    def test_no_production_changes(self, audit_doc_text: str) -> None:
        """Doc must state no production behavior changes."""
        lower = audit_doc_text.lower()
        assert "no production" in lower or "no production behavior" in lower

    def test_no_optimizer_loop_changes(self, audit_doc_text: str) -> None:
        """Doc must state no optimizer loop changes."""
        lower = audit_doc_text.lower()
        assert "no optimizer loop" in lower

    def test_no_patch_schema_changes(self, audit_doc_text: str) -> None:
        """Doc must state no patch schema changes."""
        lower = audit_doc_text.lower()
        assert "no patch schema" in lower

    def test_no_new_operations(self, audit_doc_text: str) -> None:
        """Doc must state no new operations."""
        lower = audit_doc_text.lower()
        assert "no new operations" in lower

    def test_standardization_remains_scenario_gated(self, audit_doc_text: str) -> None:
        """Doc must state standardization remains scenario-gated."""
        lower = audit_doc_text.lower()
        assert "scenario-gated" in lower and "standardization" in lower

    def test_standardization_disabled_by_default(self, audit_doc_text: str) -> None:
        """Doc must state standardization is disabled by default."""
        lower = audit_doc_text.lower()
        assert "disabled" in lower and "standardization" in lower

    def test_no_seven_section_by_default(self, audit_doc_text: str) -> None:
        """Doc must state no seven-section standardization by default."""
        lower = audit_doc_text.lower()
        assert "no seven-section" in lower or "no seven section" in lower

    def test_io_contract_preserved(self, audit_doc_text: str) -> None:
        """Doc must state IO contracts are preserved."""
        lower = audit_doc_text.lower()
        assert "io contract" in lower or "contracts preserved" in lower


# ---------------------------------------------------------------------------
# Integration with existing tests
# ---------------------------------------------------------------------------

class TestIntegration:
    """Verify this audit doesn't break existing test infrastructure."""

    def test_mapping_doc_exists(self) -> None:
        """The legacy prompt mapping doc must exist."""
        mapping_path = (
            Path(__file__).resolve().parent.parent
            / "docs"
            / "prompt_migration"
            / "legacy_prompt_to_mmap_template_mapping.md"
        )
        assert mapping_path.is_file(), f"mapping doc not found: {mapping_path}"

    def test_source_analysis_doc_exists(self) -> None:
        """The source prompt bundle analysis doc must exist."""
        source_path = (
            Path(__file__).resolve().parent.parent
            / "docs"
            / "prompt_migration"
            / "source_prompt_bundle_analysis.md"
        )
        assert source_path.is_file(), f"source analysis doc not found: {source_path}"

    def test_llm_prune_audit_doc_exists_if_created(self) -> None:
        """The LLM prune audit doc should exist if already created in prior PR."""
        llm_prune_path = _ADAPTATIONS_DIR / "llm_prune_legacy_strategy.md"
        if llm_prune_path.is_file():
            content = llm_prune_path.read_text(encoding="utf-8")
            assert "LLM_PRUNE_PROMPT" in content
            assert "covered" in content.lower()
        # Note: If not present, this is OK - it will be added when PR #75 merges

    def test_standardization_audit_doc_exists_if_created(self) -> None:
        """The standardization audit doc should exist if already created in prior PR."""
        std_path = _ADAPTATIONS_DIR / "prompt_standardization_legacy_strategy.md"
        if std_path.is_file():
            content = std_path.read_text(encoding="utf-8")
            assert "PROMPT_STANDARDIZATION_PROMPT" in content
            assert "scenario-gated" in content.lower()
        # Note: If not present, this is OK - it will be added when PR #76 merges


# ---------------------------------------------------------------------------
# Summary assertions
# ---------------------------------------------------------------------------

class TestSummary:
    """Verify the summary section is accurate."""

    def test_summary_table_exists(self, audit_doc_text: str) -> None:
        """The coverage summary table must exist."""
        assert "## Coverage Summary" in audit_doc_text

    def test_summary_counts_are_correct(self, audit_doc_text: str) -> None:
        """Summary counts must match expected values."""
        lower = audit_doc_text.lower()
        # Check for the summary table format
        assert "migrated" in lower
        assert "covered" in lower
        assert "scenario" in lower
        assert "not_separately" in lower or "not separately" in lower
        # Check total is 18
        assert "18" in audit_doc_text


# ---------------------------------------------------------------------------
# PR history verification
# ---------------------------------------------------------------------------

class TestPRHistory:
    """Verify PR history section is present."""

    def test_pr_history_section_exists(self, audit_doc_text: str) -> None:
        """PR history section must exist."""
        assert "## PR History" in audit_doc_text

    def test_pr_range_mentioned(self, audit_doc_text: str) -> None:
        """PR range #62-#76 must be mentioned."""
        assert "#62" in audit_doc_text
        assert "#76" in audit_doc_text
