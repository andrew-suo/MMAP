"""Pattern-library tests: Compression Reverse-Recovery pattern.

These tests verify the **presence and completeness** of the pattern contract
document. They do not execute any LLM. They only verify the written contract in
`docs/prompt_migration/pattern_library/compression_reverse_recovery_pattern.md`
and its registration in `docs/prompt_migration/pattern_library/README.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PATTERN_DIR = Path(__file__).resolve().parents[1] / "docs" / "prompt_migration" / "pattern_library"
DOC_PATH = PATTERN_DIR / "compression_reverse_recovery_pattern.md"
README_PATH = PATTERN_DIR / "README.md"


@pytest.fixture(scope="module")
def pattern_document() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme_document() -> str:
    return README_PATH.read_text(encoding="utf-8")


def test_pattern_document_exists() -> None:
    assert DOC_PATH.is_file(), f"missing pattern doc: {DOC_PATH}"


def test_readme_exists() -> None:
    assert README_PATH.is_file(), f"missing pattern library README: {README_PATH}"


def test_readme_registers_compression_reverse_recovery(readme_document: str) -> None:
    assert (
        "compression-reverse-recovery" in readme_document
        or "Compression Reverse-Recovery" in readme_document
    ), "README must register the compression-reverse-recovery pattern by name"


def test_pattern_declares_version(pattern_document: str) -> None:
    assert "version" in pattern_document, (
        "doc must declare a version string somewhere (e.g., in the report JSON)"
    )


def test_pattern_declares_default_enabled_false(pattern_document: str) -> None:
    assert "Default enabled" in pattern_document and "false" in pattern_document, (
        "doc must explicitly declare Default enabled: false"
    )


def test_pattern_declares_id(pattern_document: str) -> None:
    assert "compression-reverse-recovery" in pattern_document, (
        "doc must declare its pattern ID"
    )


def test_compression_budget_contract_is_documented(pattern_document: str) -> None:
    assert "Compression Budget Contract" in pattern_document, (
        "doc must document the Compression Budget Contract"
    )


def test_min_target_max_lines_are_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "min_lines" in lower
        and "target_lines" in lower
        and "max_lines" in lower
    ), "doc must document min_lines / target_lines / max_lines budget fields"


def test_over_compression_red_alert_is_documented(pattern_document: str) -> None:
    assert (
        "Over-compression Red Alert" in pattern_document
        or "Red Alert" in pattern_document
        or "red alert" in pattern_document.lower()
    ), "doc must document the over-compression red-alert behavior"


def test_reverse_recovery_add_back_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "reverse" in lower and "recover" in lower
        or "reverse" in lower and "add-back" in lower
        or "reverse" in lower and "add back" in lower
    ), "doc must document the reverse-recovery / add-back step"


def test_hard_constraints_preservation_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "hard constraint" in lower or "hard-constraint" in lower, (
        "doc must require hard constraints to survive compression"
    )


def test_output_schema_preservation_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "output schema" in lower
        or "output-schema" in lower
        or "output format" in lower
    ), "doc must require the output schema to survive compression"


def test_decision_rules_preservation_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "decision rule" in lower
        or "decision-rule" in lower
        or "decision logic" in lower
    ), "doc must require decision rules to survive compression"


def test_placeholder_preservation_is_documented(pattern_document: str) -> None:
    assert "Placeholder" in pattern_document, (
        "doc must require placeholder-token preservation"
    )


def test_icl_marker_preservation_is_documented(pattern_document: str) -> None:
    assert (
        "ICL" in pattern_document
        or "示例开始" in pattern_document
        or "示例结束" in pattern_document
    ), "doc must require ICL-marker preservation"


def test_no_core_logic_deletion_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "no core logic deletion" in lower
        or "not delete core decision logic" in lower
        or "not drop a rule that defines the pass" in lower
        or "never drop a rule" in lower
    ), "doc must forbid deletion of core decision logic"


def test_no_output_format_deletion_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "not drop output" in lower
        or "not drop the output schema" in lower
        or "not drop output schema" in lower
        or "not delete the output schema" in lower
        or "no output-format deletion" in lower
        or "forbidden" in lower and "output schema" in lower
    ), "doc must forbid deletion of output format / output schema constraints"


def test_semantic_audit_criteria_is_documented(pattern_document: str) -> None:
    assert "Semantic Audit Criteria" in pattern_document, (
        "doc must document the semantic audit criteria section"
    )


def test_three_dimension_audit_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "completeness" in lower, "doc must document the completeness dimension"
    assert (
        "constraint" in lower and "preserv" in lower
    ), "doc must document the constraint-preservation dimension"
    assert (
        "ambiguity" in lower and "reduction" in lower
        or "ambiguity" in lower and "not increase" in lower
    ), "doc must document the ambiguity-reduction dimension"


def test_compression_report_is_documented(pattern_document: str) -> None:
    assert "Compression Report" in pattern_document, (
        "doc must document the compression report structure"
    )


def test_compression_report_fields_are_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "original_length" in lower or "original length" in lower, (
        "doc must document the original-length report field"
    )
    assert "compressed_length" in lower or "compressed length" in lower, (
        "doc must document the compressed-length report field"
    )
    assert "removed_items" in lower or "removed items" in lower, (
        "doc must document the removed-items report field"
    )
    assert (
        "preserved_critical_items" in lower
        or "preserved critical items" in lower
        or "preserved-critical" in lower
    ), "doc must document the preserved-critical-items report field"
    assert "recovered_items" in lower or "recovered items" in lower, (
        "doc must document the recovered-items report field"
    )
    assert "risk_level" in lower or "risk level" in lower, (
        "doc must document the risk-level report field"
    )


def test_examples_section_is_present(pattern_document: str) -> None:
    assert "## Examples" in pattern_document, "doc must include an ## Examples section"


def test_anti_examples_section_is_present(pattern_document: str) -> None:
    assert (
        "## Anti-examples" in pattern_document
        or "## Anti examples" in pattern_document
    ), "doc must include an ## Anti-examples section"


def test_self_check_checklist_is_present(pattern_document: str) -> None:
    assert (
        "## Self-check Checklist" in pattern_document
        or "## Self-check checklist" in pattern_document
        or "Self-check" in pattern_document and "checklist" in pattern_document.lower()
    ), "doc must include a self-check checklist section"


def test_test_contract_section_is_present(pattern_document: str) -> None:
    assert "## Test Contract" in pattern_document, (
        "doc must include a ## Test Contract section"
    )


def test_document_has_when_to_use_section(pattern_document: str) -> None:
    assert "## When to Use" in pattern_document, "doc must include ## When to Use"


def test_document_has_when_not_to_use_section(pattern_document: str) -> None:
    assert "## When Not to Use" in pattern_document, (
        "doc must include ## When Not to Use"
    )


def test_document_has_source_legacy_prompts_section(pattern_document: str) -> None:
    assert "Source Legacy Prompts" in pattern_document, (
        "doc must cite the legacy prompts it is derived from"
    )


def test_document_has_allowed_and_forbidden_sections(pattern_document: str) -> None:
    assert "Allowed Transformations" in pattern_document, (
        "doc must include an Allowed Transformations section"
    )
    assert "Forbidden Transformations" in pattern_document, (
        "doc must include a Forbidden Transformations section"
    )


def test_document_does_not_prescribe_default_prompt_replacement(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "replace the default prompt" not in lower, (
        "doc must not prescribe replacing the default prompt"
    )


def test_document_has_migration_notes(pattern_document: str) -> None:
    assert "## Migration Notes" in pattern_document, (
        "doc must include a ## Migration Notes section"
    )


def test_document_is_substantially_long(pattern_document: str) -> None:
    non_blank = [ln for ln in pattern_document.splitlines() if ln.strip()]
    assert len(non_blank) >= 60, (
        f"pattern doc suspiciously short: only {len(non_blank)} non-blank lines"
    )


def test_document_references_its_matching_test_file(pattern_document: str) -> None:
    assert "test_pattern_library_compression_reverse_recovery" in pattern_document, (
        "doc must reference its matching test file by name"
    )


def test_no_generalization_into_vague_rules_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "general" in lower and "vague" in lower
        or "never replace" in lower and "concrete" in lower
        or "no rule-generalization" in lower
        or "generalization" in lower
    ), "doc must forbid replacing concrete rules with vague descriptions"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
