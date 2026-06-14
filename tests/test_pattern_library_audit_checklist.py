"""Pattern-library tests: Audit Checklist pattern.

These tests verify the **presence and completeness** of the pattern contract
document. They do not execute any LLM. They only verify the written contract in
`docs/prompt_migration/pattern_library/audit_checklist_pattern.md` and its
registration in `docs/prompt_migration/pattern_library/README.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PATTERN_DIR = Path(__file__).resolve().parents[1] / "docs" / "prompt_migration" / "pattern_library"
DOC_PATH = PATTERN_DIR / "audit_checklist_pattern.md"
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


def test_readme_registers_audit_checklist(readme_document: str) -> None:
    assert (
        "audit-checklist" in readme_document
        or "Audit Checklist" in readme_document
    ), "README must register the audit-checklist pattern by name"


def test_pattern_declares_version(pattern_document: str) -> None:
    assert "version" in pattern_document, (
        "doc must declare a version string somewhere (e.g., in the audit JSON)"
    )


def test_pattern_declares_default_enabled_false(pattern_document: str) -> None:
    assert "Default enabled" in pattern_document and "false" in pattern_document, (
        "doc must explicitly declare Default enabled: false"
    )


def test_pattern_declares_id(pattern_document: str) -> None:
    assert "audit-checklist" in pattern_document, (
        "doc must declare its pattern ID"
    )


def test_audit_target_is_documented(pattern_document: str) -> None:
    assert "Audit Target" in pattern_document or "audit target" in pattern_document.lower(), (
        "doc must document the audit target"
    )


def test_audit_dimensions_are_documented(pattern_document: str) -> None:
    assert "Audit Dimension" in pattern_document or "audit dimension" in pattern_document.lower(), (
        "doc must document the audit dimensions"
    )


def test_pass_warning_fail_semantics_are_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "pass" in lower and "warn" in lower and "fail" in lower, (
        "doc must document PASS / WARN / FAIL semantics"
    )


def test_evidence_requirement_is_documented(pattern_document: str) -> None:
    assert (
        "Evidence Requirement" in pattern_document
        or "evidence requirement" in pattern_document.lower()
        or "evidence" in pattern_document.lower()
    ), "doc must document the evidence requirement"


def test_no_silent_pass_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "no silent pass" in lower
        or "never pass without" in lower
        or "must not pass without" in lower
        or "cannot pass without" in lower
        or "must have evidence" in lower
    ), "doc must forbid passing a dimension without evidence"


def test_hard_constraint_strictness_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "hard constraint" in lower
        or "hard-constraint" in lower
        or "hard constraints" in lower
    ), "doc must document hard-constraint strictness"


def test_audit_is_read_only_unless_repair_mode(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "read only" in lower
        or "read-only" in lower
        or "not mutate" in lower
        or "not modify" in lower
        or "not write" in lower
    ), "doc must state that the audit step must not modify the target (unless a separate repair step)"


def test_checklist_item_schema_is_documented(pattern_document: str) -> None:
    assert "Checklist Item Schema" in pattern_document or "item schema" in pattern_document.lower(), (
        "doc must document the checklist item schema"
    )


def test_checklist_item_schema_fields_are_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    for field in ("id", "dimension", "status", "evidence", "issue", "severity", "suggested_fix"):
        assert field in lower, f"doc must document the checklist schema field: {field}"


def test_severity_levels_are_documented(pattern_document: str) -> None:
    assert "Severity Level" in pattern_document or "severity level" in pattern_document.lower(), (
        "doc must document severity levels"
    )


def test_blocker_major_minor_info_are_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "blocker" in lower, "doc must document 'blocker' severity"
    assert "major" in lower, "doc must document 'major' severity"
    assert "minor" in lower, "doc must document 'minor' severity"
    assert "info" in lower, "doc must document 'info' severity"


def test_failure_summary_is_documented(pattern_document: str) -> None:
    assert (
        "Failure Summary" in pattern_document
        or "failure summary" in pattern_document.lower()
    ), "doc must document the failure summary"


def test_repair_recommendation_is_documented(pattern_document: str) -> None:
    assert (
        "Repair Recommendation" in pattern_document
        or "repair recommendation" in pattern_document.lower()
    ), "doc must document the repair recommendation field"


def test_machine_readable_output_is_documented(pattern_document: str) -> None:
    assert (
        "Machine-readable Output" in pattern_document
        or "machine-readable" in pattern_document.lower()
    ), "doc must document the machine-readable JSON output"


def test_human_readable_output_is_documented(pattern_document: str) -> None:
    assert (
        "Human-readable Output" in pattern_document
        or "human-readable" in pattern_document.lower()
        or "human readable" in pattern_document.lower()
    ), "doc must document the human-readable summary output"


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
    assert "test_pattern_library_audit_checklist" in pattern_document, (
        "doc must reference its matching test file by name"
    )


def test_document_explains_evidence_is_required_for_pass(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "evidence" in lower and "pass" in lower
        or "evidence" in pattern_document and "PASS" in pattern_document
    ), "doc must explain that a PASS requires evidence"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
