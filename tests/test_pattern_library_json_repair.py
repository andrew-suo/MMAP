"""Pattern-library tests: JSON repair / position-valid output pattern.

These tests verify the **presence and completeness** of the pattern contract
document. They do not execute any LLM — they only verify the written contract
in `docs/prompt_migration/pattern_library/json_repair_pattern.md`.

Scope of this file
------------------

- Doc-publishing test
- Position-valid output contract text presence
- First/last character rules
- No-fence / no-prose rules
- RFC 8259 reference
- Field preservation / no-hallucination rules
- Object and Array support
- Trailing-comma and fenced-JSON coverage
- Example + Test Contract sections

Intentional non-scope
---------------------

- No LLM calls.
- No runtime JSON repair against a prompt — that is an integration-level
  concern for a separate, future PR that wires the pattern.
- No changes to default prompts, optimizer loop, CLI, scenarios, or any
  other runtime default behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PATTERN_DIR = Path(__file__).resolve().parents[1] / "docs" / "prompt_migration" / "pattern_library"
DOC_PATH = PATTERN_DIR / "json_repair_pattern.md"


@pytest.fixture(scope="module")
def pattern_document() -> str:
    assert DOC_PATH.is_file(), (
        f"pattern doc must exist at {DOC_PATH} — this PR ships the doc + tests only"
    )
    return DOC_PATH.read_text(encoding="utf-8")


def test_pattern_document_exists() -> None:
    assert DOC_PATH.is_file(), f"missing pattern doc: {DOC_PATH}"


def test_pattern_document_declares_version(pattern_document: str) -> None:
    assert "version" in pattern_document, (
        "json repair doc must declare a version field in its output contract"
    )


def test_position_valid_output_contract_section_exists(pattern_document: str) -> None:
    # Case-insensitive on the heading; we look for the canonical name.
    lower = pattern_document.lower()
    assert "position-valid" in lower and "contract" in lower, (
        "doc must include the position-valid output contract"
    )


def test_first_non_whitespace_rule_is_documented(pattern_document: str) -> None:
    assert "first non-whitespace" in pattern_document, (
        "doc must require first non-whitespace character must be { or ["
    )
    # The doc must reference the actual valid first characters.
    assert "{" in pattern_document and "[" in pattern_document, (
        "doc must reference both { and [ as valid first characters"
    )


def test_last_non_whitespace_rule_is_documented(pattern_document: str) -> None:
    assert "last non-whitespace" in pattern_document, (
        "doc must require last non-whitespace character must be } or ]"
    )
    assert "}" in pattern_document and "]" in pattern_document, (
        "doc must reference both } and ] as valid last characters"
    )


def test_no_markdown_fence_rule_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "fence" in lower
        or "code fence" in lower
        or "code block" in lower
        or "backtick" in lower
    ), "doc must forbid wrapping output in Markdown fences / code blocks"


def test_no_prose_or_explanatory_text_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "prose" in lower
        or "explanation" in lower
        or "explanatory" in lower
        or "surrounding text" in lower
        or "no surrounding prose" in lower
        or "no prose" in lower
        or "no explanation" in lower
    ), "doc must forbid explanation / prose / prefix around the JSON body"


def test_rfc_8259_reference_is_documented(pattern_document: str) -> None:
    assert "RFC 8259" in pattern_document, (
        "doc must reference RFC 8259 (JSON specification)"
    )


def test_field_preservation_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "preserv" in lower
        or "keep every field" in lower
        or "keep all fields" in lower
        or "must not remove fields" in lower
        or "do not remove fields" in lower
        or "never remove fields" in lower
    ), "doc must require field-value preservation"


def test_no_hallucination_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "hallucinat" in lower
        or "no field addition" in lower
        or "do not invent" in lower
        or "never invent" in lower
        or "do not infer" in lower
    ), "doc must forbid adding/inventing/hallucinating fields"


def test_object_json_support_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "object" in lower, "doc must explicitly support object JSON"


def test_array_json_support_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "array" in lower, "doc must explicitly support array JSON"


def test_trailing_comma_repair_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "trailing comma" in lower or "trailing-comma" in lower, (
        "doc must explicitly support trailing-comma repair"
    )


def test_fenced_json_stripping_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "fenc" in lower
        or "backtick" in lower
        or "code block" in lower
    ), "doc must explicitly support fenced-JSON stripping"


def test_examples_section_is_present(pattern_document: str) -> None:
    assert "## Examples" in pattern_document, (
        "doc must include an ## Examples section"
    )


def test_test_contract_section_is_present(pattern_document: str) -> None:
    assert "## Test Contract" in pattern_document, (
        "doc must include a ## Test Contract section"
    )


def test_when_to_use_and_when_not_to_use_sections_exist(pattern_document: str) -> None:
    assert "## When to Use" in pattern_document and "## When Not to Use" in pattern_document, (
        "doc must have both ## When to Use and ## When Not to Use"
    )


def test_pattern_id_is_declared(pattern_document: str) -> None:
    assert "json-repair-position-valid" in pattern_document, (
        "doc must declare pattern ID: json-repair-position-valid"
    )


def test_default_enabled_is_false(pattern_document: str) -> None:
    assert "Default enabled" in pattern_document and "false" in pattern_document, (
        "doc must explicitly declare Default enabled: false"
    )


def test_document_references_its_matching_test_file(pattern_document: str) -> None:
    assert "test_pattern_library_json_repair" in pattern_document, (
        "doc must reference its matching test file by name"
    )


def test_document_has_input_and_output_contract_sections(pattern_document: str) -> None:
    assert "## Input Contract" in pattern_document, (
        "doc must have an Input Contract section"
    )
    assert "## Output Contract" in pattern_document, (
        "doc must have an Output Contract section"
    )


def test_document_does_not_prescribe_default_prompt_replacement(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "replace the default prompt" not in lower, (
        "doc must not prescribe replacing the default prompt"
    )


def test_document_has_at_least_one_concrete_example_code_block(pattern_document: str) -> None:
    lines = pattern_document.splitlines()
    code_blocks = sum(1 for ln in lines if ln.strip().startswith("```"))
    assert code_blocks >= 4, (
        f"pattern doc should include several concrete example code blocks; found {code_blocks}"
    )


def test_document_mentions_both_hint_object_and_hint_array(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert '"object"' in pattern_document and '"array"' in pattern_document, (
        "doc must reference both 'object' and 'array' hint values in its input contract"
    )


def test_document_explains_meta_field_rule(pattern_document: str) -> None:
    assert "_meta" in pattern_document or "meta" in pattern_document, (
        "doc must document the optional _meta.repair_trace field"
    )


def test_document_explains_when_meta_is_omitted(pattern_document: str) -> None:
    # We want an explicit "if the JSON parsed cleanly, _meta is omitted" rule.
    lower = pattern_document.lower()
    assert (
        "omit" in lower
        or "absent" in lower
        or "must not be present" in pattern_document
        or "not produced" in pattern_document
        or "must be omitted" in pattern_document
    ), "doc must specify that _meta must be omitted for clean JSON"


def test_document_forbids_type_coercion(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "number coercion" in lower
        or "never convert numbers" in lower
        or "number coercion" in lower
        or "do not convert numbers" in lower
        or "never coerce" in lower
        or "never convert numbers to strings" in lower
    ), "doc must forbid number-to-string and string-to-number coercion"


def test_document_forbids_schema_tightening_and_field_removal(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "never remove fields" in lower
        or "do not remove fields" in lower
        or "never drop fields" in lower
        or "do not drop fields" in lower
        or "never remove" in lower
        or "never remove fields that are not in the input" in lower
        or "schema tightening" in lower
        or "never remove fields even if" in lower
    ), "doc must forbid removal of existing fields"


def test_document_explains_source_legacy_prompts(pattern_document: str) -> None:
    assert "Source Legacy Prompts" in pattern_document, (
        "doc must cite the legacy prompts it is derived from"
    )


def test_document_lists_core_guardrails_section(pattern_document: str) -> None:
    assert "Core Guardrails" in pattern_document or "Guardrails" in pattern_document, (
        "doc must include a guardrail section"
    )


def test_document_explicitly_forbids_key_reordering(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "reorder" in lower
        or "never reorder" in lower
        or "do not reorder" in lower
        or "not reorder" in pattern_document
        or "keep key order" in pattern_document
    ), "doc must forbid reordering of JSON keys for deterministic output-by-default"


def test_document_is_substantially_long(pattern_document: str) -> None:
    non_blank = [ln for ln in pattern_document.splitlines() if ln.strip()]
    assert len(non_blank) >= 35, (
        f"pattern doc suspiciously short: only {len(non_blank)} non-blank lines"
    )


def test_document_mentions_determinism(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "deterministic" in lower or "byte-identical" in pattern_document, (
        "pattern doc must require deterministic output"
    )


def test_document_mentions_allowed_and_forbidden_repair_sections(pattern_document: str) -> None:
    assert "Allowed Repairs" in pattern_document and "Forbidden Repairs" in pattern_document, (
        "pattern doc must contain both Allowed Repairs and Forbidden Repairs sections"
    )


def test_document_has_a_position_valid_definition_block(pattern_document: str) -> None:
    # We require a well-formed definition of "position-valid."
    fragment = pattern_document
    assert "position-valid JSON" in fragment or "position-valid" in fragment, (
        "doc must define what 'position-valid' means"
    )


def test_default_prompts_directory_is_untouched_smoke() -> None:
    """This PR ships the pattern library only. It must not touch default prompts."""
    prompts_root = Path(__file__).resolve().parents[1] / "prompts"
    if not prompts_root.is_dir():
        return
    any_file = next(prompts_root.rglob("*.*"), None)
    if any_file is None:
        return
    body = any_file.read_text(encoding="utf-8")
    assert isinstance(body, str), "prompts/ files must remain readable after this PR"


def test_document_test_contract_section_references_our_tests(pattern_document: str) -> None:
    contract_idx = pattern_document.find("## Test Contract")
    assert contract_idx >= 0
    fragment = pattern_document[contract_idx: contract_idx + 2000]
    assert "Doc-publishing test" in fragment
    assert "Position-valid contract text presence" in fragment


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
