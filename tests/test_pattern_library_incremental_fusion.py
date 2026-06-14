"""Pattern-library tests: Incremental Fusion pattern.

These tests verify the **presence and completeness** of the pattern contract
document. They do not execute any LLM. They only verify the written contract in
`docs/prompt_migration/pattern_library/incremental_fusion_pattern.md` and its
registration in `docs/prompt_migration/pattern_library/README.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PATTERN_DIR = Path(__file__).resolve().parents[1] / "docs" / "prompt_migration" / "pattern_library"
DOC_PATH = PATTERN_DIR / "incremental_fusion_pattern.md"
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


def test_readme_registers_incremental_fusion(readme_document: str) -> None:
    assert (
        "incremental-fusion" in readme_document
        or "Incremental Fusion" in readme_document
    ), "README must register the incremental-fusion pattern by name"


def test_pattern_declares_version(pattern_document: str) -> None:
    assert "version" in pattern_document, (
        "doc must declare a version string somewhere (e.g., in the change summary JSON)"
    )


def test_pattern_declares_default_enabled_false(pattern_document: str) -> None:
    assert "Default enabled" in pattern_document and "false" in pattern_document, (
        "doc must explicitly declare Default enabled: false"
    )


def test_pattern_declares_id(pattern_document: str) -> None:
    assert "incremental-fusion" in pattern_document, (
        "doc must declare its pattern ID: incremental-fusion"
    )


def test_incremental_fusion_weaving_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "weave" in lower
        or "weaving" in lower
        or "incremental fusion" in lower
        or "incrementally" in lower
        or "增量" in pattern_document
    ), "doc must reference incremental fusion / weaving of new rules"


def test_no_wholesale_replacement_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "not replace" in lower
        or "do not replace" in lower
        or "not wholesale" in lower
        or "no wholesale" in lower
        or "not rewrite" in lower
        or "not delete the original rule" in lower
        or "silently delete" in lower
        or "silent deletion" in lower
        or "silent override" in lower
    ), "doc must forbid wholesale replacement that silently drops old rules"


def test_preserve_existing_rules_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "preserv" in lower and "rule" in lower
        or "keep existing rules" in lower
        or "keep the original rule" in lower
        or "original rule" in pattern_document and "preserved" in pattern_document
        or "byte-identical" in pattern_document
    ), "doc must require existing rules to be preserved"


def test_conflict_marker_is_documented(pattern_document: str) -> None:
    assert (
        "CONFLICT" in pattern_document
        or "conflict" in pattern_document.lower()
    ), "doc must require explicit conflict marking"


def test_no_silent_weak_constraint_deletion_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "not silent" in lower
        or "silent deletion" in lower
        or "silently delete" in lower
        or "do not drop" in lower
        or "weak constraint" in lower
    ), "doc must forbid silent deletion of weak constraints"


def test_no_silent_strong_constraint_override_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "not silent" in lower
        or "silent override" in lower
        or "silently override" in lower
        or "do not override" in lower
        or "strong constraint" in lower
    ), "doc must forbid silent override of strong constraints"


def test_frozen_section_protection_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "frozen" in lower or "[FROZEN]" in pattern_document, (
        "doc must document frozen-section protection"
    )


def test_icl_marker_preservation_is_documented(pattern_document: str) -> None:
    assert (
        "ICL" in pattern_document
        or "示例开始" in pattern_document
        or "示例结束" in pattern_document
    ), "doc must document ICL marker preservation"


def test_output_schema_preservation_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "schema" in lower and "preserv" in lower
        or "output schema" in pattern_document and "preserve" in pattern_document
        or "do not change" in lower and "output schema" in lower
    ), "doc must document output schema preservation"


def test_change_summary_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "change summary" in lower
        or "change-summary" in lower
        or "变更摘要" in pattern_document
    ), "doc must document the change summary output"


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


def test_document_mentions_determinism(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "deterministic" in lower or "determinism" in lower, (
        "doc must require deterministic output"
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
    assert len(non_blank) >= 50, (
        f"pattern doc suspiciously short: only {len(non_blank)} non-blank lines"
    )


def test_document_references_its_matching_test_file(pattern_document: str) -> None:
    assert "test_pattern_library_incremental_fusion" in pattern_document, (
        "doc must reference its matching test file by name"
    )


def test_document_mentions_conflict_marker_is_greppable(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "marker" in lower
        or "greppable" in lower
        or "[CONFLICT" in pattern_document
    ), "doc must reference the conflict marker (greppable string)"


def test_document_forbids_output_schema_change(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "not change" in lower and "output schema" in lower
        or "not add" in lower and "output schema" in lower
        or "not rename" in lower and "output schema" in lower
        or "not remove" in lower and "output schema" in lower
        or "output schema preservation" in pattern_document.lower()
        or "output schema must" in pattern_document.lower()
    ), "doc must forbid adding / removing / renaming output schema fields"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
