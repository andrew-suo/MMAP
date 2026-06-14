"""Pattern-library tests: Immutable Payload pattern.

These tests verify the **presence and completeness** of the pattern contract
document. They do not execute any LLM. They only verify the written contract in
`docs/prompt_migration/pattern_library/immutable_payload_pattern.md` and its
registration in `docs/prompt_migration/pattern_library/README.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PATTERN_DIR = Path(__file__).resolve().parents[1] / "docs" / "prompt_migration" / "pattern_library"
DOC_PATH = PATTERN_DIR / "immutable_payload_pattern.md"
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


def test_readme_registers_immutable_payload(readme_document: str) -> None:
    assert (
        "immutable-payload" in readme_document
        or "Immutable Payload" in readme_document
    ), "README must register the immutable-payload pattern by name"


def test_pattern_declares_version(pattern_document: str) -> None:
    assert "version" in pattern_document, (
        "doc must declare a version string somewhere (e.g., in the output contract JSON)"
    )


def test_pattern_declares_default_enabled_false(pattern_document: str) -> None:
    assert "Default enabled" in pattern_document and "false" in pattern_document, (
        "doc must explicitly declare Default enabled: false"
    )


def test_pattern_declares_id(pattern_document: str) -> None:
    assert "immutable-payload" in pattern_document, (
        "doc must declare its pattern ID: immutable-payload"
    )


def test_mutable_vs_immutable_boundary_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "mutable" in lower and "immutable" in lower
    ), "doc must document the mutable-vs-immutable boundary"


def test_placeholder_protection_is_documented(pattern_document: str) -> None:
    assert "Placeholder Protection" in pattern_document, (
        "doc must have a Placeholder Protection section"
    )


def test_all_core_placeholder_tokens_are_listed(pattern_document: str) -> None:
    for token in (
        "{question}",
        "{answer}",
        "{label}",
        "{prediction}",
        "{reference}",
        "{context}",
        "{input}",
        "{output}",
    ):
        assert token in pattern_document, (
            f"doc must protect placeholder token {token}"
        )


def test_n_in_n_out_contract_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "n-in-n-out" in pattern_document
        or "n in n out" in lower
        or "n-in-n-out" in lower
    ), "doc must document the N-in-N-out contract"


def test_order_preservation_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "order" in lower and "preserv" in lower, (
        "doc must document order preservation within each payload unit"
    )


def test_no_semantic_drift_guardrail_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "semantic" in lower
        or "do not change the business" in lower
        or "payload" in lower and "preserv" in lower
    ), "doc must forbid payload semantic drift / business rule changes"


def test_no_field_rename_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "do not rename" in lower
        or "never rename" in lower
        or "renam" in lower and "field" in lower
        or "no field renaming" in lower
    ), "doc must forbid field / variable renaming"


def test_no_placeholder_tampering_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "placeholder" in lower
        and ("do not delete" in lower or "never delete" in lower or "preserv" in lower)
    ), "doc must forbid placeholder renaming / deletion"


def test_no_constraint_deletion_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "do not delete" in lower
        or "never delete" in lower
        or "forbidden" in lower and "delet" in lower
        or "no rule deletion" in lower
    ), "doc must forbid deleting original constraints or rules"


def test_no_hallucinated_rules_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "do not add" in lower
        or "never add" in lower
        or "hallucinat" in lower
        or "no new business rule" in lower
        or "forbidden" in lower and "add" in lower
    ), "doc must forbid adding new business rules to the payload"


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


def test_document_does_not_enable_7section_standardization(pattern_document: str) -> None:
    assert "7-section standardization" not in pattern_document or (
        "never" in pattern_document.lower() or "do not" in pattern_document.lower()
    ), "doc must not enable 7-section standardization"


def test_document_does_not_enable_3state_evaluation(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "3-state" not in pattern_document
        or "not" in lower
        or "never" in lower
    ), "doc must not enable 3-state evaluation"


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
    assert "test_pattern_library_immutable_payload" in pattern_document, (
        "doc must reference its matching test file by name"
    )


def test_document_mentions_icl_markers(pattern_document: str) -> None:
    # The pattern must preserve ICL marker tokens.
    assert (
        "ICL" in pattern_document
        or "示例开始" in pattern_document
        or "示例结束" in pattern_document
    ), "doc must mention ICL marker preservation (compose with #2 pattern)"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
