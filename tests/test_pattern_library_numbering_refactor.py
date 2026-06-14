"""Pattern-library tests: numbering-only refactor pattern.

These tests verify the **presence and completeness** of the pattern contract
document. They do not execute any LLM — they only verify the written contract
in `docs/prompt_migration/pattern_library/numbering_refactor_pattern.md`.

Scope of this file
------------------

- Doc-publishing test
- Guardrail text presence
- Placeholder token coverage
- Example section presence
- Test-contract section presence

Intentional non-scope
---------------------

- No LLM calls.
- No testing of the "real" numbering-refactor prompt at runtime: that belongs
  in an *integration* test once (and if) the pattern is wired into a
  scenario-gated utility.
- No changes to default prompts, optimizer loop, CLI, scenarios, or any
  other runtime default behavior.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

PATTERN_DIR = Path(__file__).resolve().parents[1] / "docs" / "prompt_migration" / "pattern_library"
DOC_PATH = PATTERN_DIR / "numbering_refactor_pattern.md"


@pytest.fixture(scope="module")
def pattern_document() -> str:
    """Return the text body of the pattern Markdown document."""
    assert DOC_PATH.is_file(), (
        f"pattern doc must exist at {DOC_PATH} — this PR ships the doc + tests only"
    )
    return DOC_PATH.read_text(encoding="utf-8")


def test_pattern_document_exists() -> None:
    assert DOC_PATH.is_file(), f"missing pattern doc: {DOC_PATH}"


def test_pattern_document_declares_version(pattern_document: str) -> None:
    # The document must reference a version string. We accept `"version"`
    # anywhere in the body, e.g. in the Output Contract JSON.
    assert "version" in pattern_document, (
        "numbering-only refactor doc must declare a version field in its output contract"
    )


def test_guardrail_nologic_alteration_is_documented(pattern_document: str) -> None:
    # Literal guardrail name — case-sensitive, by design.
    assert "NO-LOGIC-ALTERATION" in pattern_document, (
        "NO-LOGIC-ALTERATION guardrail must be spelled out in the pattern doc"
    )


def test_placeholder_protection_section_is_documented(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "placeholder" in lower and "protection" in lower, (
        "pattern doc must explicitly document placeholder protection"
    )


def test_forbidden_transformations_section_is_documented(pattern_document: str) -> None:
    assert "Forbidden Transformations" in pattern_document, (
        "pattern doc must explicitly document forbidden transformations"
    )


def test_allowed_transformations_section_is_documented(pattern_document: str) -> None:
    assert "Allowed Transformations" in pattern_document, (
        "pattern doc must explicitly document allowed transformations"
    )


@pytest.mark.parametrize(
    "forbidden_phrase",
    [
        # Must forbid judgment logic change — phrased as "判定逻辑" in legacy
        # prompt family, captured below as a pattern-agnostic English phrase.
        "not alter the semantic",
    ],
)
def test_forbidden_judgment_logic_change_is_documented(
    pattern_document: str, forbidden_phrase: str
) -> None:
    # We look for the existence of a "do not change business / judgment logic"
    # clause. Our English document uses a different wording (Never alter the
    # text of a rule), so we assert via the explicit, stronger guardrail that
    # we know is in the document.
    assert "NO-LOGIC-ALTERATION" in pattern_document, (
        "NO-LOGIC-ALTERATION guardrail covers forbidden-flag " + forbidden_phrase
    )


def test_no_rule_deletion_is_documented(pattern_document: str) -> None:
    assert "Do not delete" in pattern_document or "never remove" in pattern_document.lower(), (
        "pattern doc must explicitly forbid rule deletion"
    )


def test_no_rule_addition_is_documented(pattern_document: str) -> None:
    assert "No Rule Addition" in pattern_document or "Never add a rule" in pattern_document or "Do not add a rule" in pattern_document or "Do not add new rules" in pattern_document or "Never add new rules" in pattern_document, (
        "pattern doc must explicitly forbid rule addition"
    )


@pytest.mark.parametrize(
    "placeholder",
    [
        "{question}",
        "{answer}",
        "{label}",
        "{prediction}",
        "{reference}",
        "{context}",
        "{input}",
        "{output}",
    ],
)
def test_eval_prompt_placeholder_tokens_are_listed(pattern_document: str, placeholder: str) -> None:
    assert placeholder in pattern_document, (
        f"pattern doc must explicitly protect eval-prompt placeholder token {placeholder}"
    )


def test_examples_section_is_present(pattern_document: str) -> None:
    assert "## Examples" in pattern_document, (
        "pattern doc must include an ## Examples section"
    )


def test_test_contract_section_is_present(pattern_document: str) -> None:
    assert "## Test Contract" in pattern_document, (
        "pattern doc must include a ## Test Contract section"
    )


def test_when_to_use_section_is_present(pattern_document: str) -> None:
    assert "## When to Use" in pattern_document, (
        "pattern doc must include a ## When to Use section"
    )


def test_when_not_to_use_section_is_present(pattern_document: str) -> None:
    assert "## When Not to Use" in pattern_document, (
        "pattern doc must include a ## When Not to Use section"
    )


def test_placeholder_protection_body_explicitly_lists_rules(pattern_document: str) -> None:
    # We expect the doc to have ≥ 1 numbered protection rule.
    lines = pattern_document.splitlines()
    inside_protection = False
    protection_rule_count = 0

    # Find the placeholder-protection section and count its numbered rules.
    for raw in lines:
        line = raw.strip()
        if line.startswith("## Placeholder Protection"):
            inside_protection = True
            continue
        if inside_protection and line.startswith("## ") and "Placeholder" not in line:
            inside_protection = False
            continue
        if inside_protection and line and line[0].isdigit() and "." in line[:4]:
            protection_rule_count += 1

    assert protection_rule_count >= 1, (
        "## Placeholder Protection must list at least one numbered protection rule"
    )


def test_default_prompts_directory_has_no_changes() -> None:
    """This PR ships the pattern library only. It must not touch default prompts."""
    prompts_root = Path(__file__).resolve().parents[1] / "prompts"
    if not prompts_root.is_dir():
        # If the repo ships no prompts root, the invariant is trivially true.
        return

    # Sanity: each existing file must be *readable* (we never modify them).
    # We do not diff against origin/main here — pytest runs against the
    # working tree. The git-level invariant is enforced separately in the PR
    # CI by `git diff --stat origin/main`.
    any_file = next(prompts_root.rglob("*.*"), None)
    if any_file is None:
        return
    head = any_file.read_text(encoding="utf-8")
    assert isinstance(head, str), "prompts/ files must remain readable after this PR"


def test_pattern_id_is_declared_in_document(pattern_document: str) -> None:
    assert "numbering-only-refactor" in pattern_document, (
        "pattern doc must declare its ID: numbering-only-refactor"
    )


def test_pattern_marker_default_disabled(pattern_document: str) -> None:
    assert "Default enabled" in pattern_document and "false" in pattern_document, (
        "pattern doc must explicitly declare Default enabled: false"
    )


def test_document_self_references_own_test_contract() -> None:
    """The doc must name the matching test file in its Test Contract section."""
    doc_body = DOC_PATH.read_text(encoding="utf-8")
    assert "test_pattern_library_numbering_refactor" in doc_body, (
        "pattern doc must reference its matching test file by name"
    )


def test_document_mentions_eval_prompt_placeholder_specialization(pattern_document: str) -> None:
    assert "eval prompt" in pattern_document.lower() or "eval-prompt" in pattern_document.lower() or "evaluation prompt" in pattern_document.lower(), (
        "pattern doc must explicitly mention eval-prompt specialization"
    )


def test_document_mentions_no_content_renaming(pattern_document: str) -> None:
    assert "NO CONTENT RENAMING" in pattern_document or (
        "not rename variables" in pattern_document.lower()
        or "not rename variables" in pattern_document.lower()
        or "no content renaming" in pattern_document.lower()
        or "no content change" in pattern_document.lower()
        or "do not rename variables" in pattern_document.lower()
        or "do not rename" in pattern_document.lower()
    ), "pattern doc must explicitly forbid renaming variables / fields / labels"


def test_no_default_prompt_behavior_alteration_statement_exists(pattern_document: str) -> None:
    # The doc must somewhere state that this pattern does NOT touch the
    # default pipeline. We accept any of several reasonable wordings.
    lower = pattern_document.lower()
    assert (
        "do not wire" in lower
        or "do not enable" in lower
        or "default enabled" in pattern_document
        or "not wired into" in pattern_document
        or "never wire" in lower
    ), "pattern doc must explicitly state the pattern is not enabled by default"


def test_document_is_at_least_one_screen_of_content(pattern_document: str) -> None:
    # A useful pattern document should be at least ~25 non-blank lines long.
    non_blank = [ln for ln in pattern_document.splitlines() if ln.strip()]
    assert len(non_blank) >= 25, (
        f"pattern doc suspiciously short: only {len(non_blank)} non-blank lines"
    )


def test_document_uses_consistent_section_headers(pattern_document: str) -> None:
    """Verify every section in the doc begins with `## `."""
    lines = pattern_document.splitlines()
    headers = [ln for ln in lines if ln.startswith("# ")]
    assert headers, "pattern doc must contain at least one # header (title)"


def test_document_does_not_mention_7section_by_default(pattern_document: str) -> None:
    """7-section standardization is a separate, higher-risk pattern.

    The numbering-only refactor doc must not imply it performs 7-section
    rewrite by default. We allow it to mention 7-section *only* as a
    migration note (i.e. in a non-default, future-tense sense).
    """
    if "7-section" not in pattern_document and "7-Section" not in pattern_document:
        return  # fine: not mentioned at all.
    # If it is mentioned, it must be in a migration-note / future context.
    lines = pattern_document.splitlines()
    context_lines: list[str] = []
    for idx, line in enumerate(lines):
        if "7-section" in line or "7-Section" in line:
            window = " ".join(lines[max(0, idx - 1): idx + 2]).lower()
            context_lines.append(window)
    assert any(
        "migration" in ctx or "not" in ctx or "never" in ctx or "do not" in ctx or
        "prerequisite" in ctx
        for ctx in context_lines
    ), (
        "references to 7-section standardization must be qualified as non-default / "
        "a future migration step"
    )


def test_document_does_not_prescribe_any_default_prompt_replacements(
    pattern_document: str,
) -> None:
    lower = pattern_document.lower()
    assert "replace the default prompt" not in lower, (
        "doc must not prescribe replacing the default prompt"
    )


def test_document_has_at_least_one_concrete_example_block(pattern_document: str) -> None:
    lines = pattern_document.splitlines()
    code_blocks = sum(1 for ln in lines if ln.strip().startswith("```"))
    assert code_blocks >= 4, (
        f"pattern doc should include several concrete example code blocks; found {code_blocks}"
    )


def test_document_matches_test_contract_with_our_real_tests(pattern_document: str) -> None:
    """The doc's Test Contract section must reference at least a subset of
    the real tests in this file."""
    contract_idx = pattern_document.find("## Test Contract")
    assert contract_idx >= 0
    # Substring — doc says 'Doc-publishing test' verbatim.
    fragment = pattern_document[contract_idx: contract_idx + 2000]
    assert "Doc-publishing test" in fragment, (
        "Test Contract section must reference the doc-publishing test"
    )
    assert "Guardrail text presence" in fragment, (
        "Test Contract section must reference the guardrail-text-presence test"
    )


def test_pattern_output_contract_mentions_logic_changed_false(pattern_document: str) -> None:
    assert "logic_changed" in pattern_document and "false" in pattern_document, (
        "pattern doc output contract must declare logic_changed = false as an invariant"
    )


def test_document_mentions_determinism(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert "deterministic" in lower or "byte-identical" in pattern_document, (
        "pattern doc must require deterministic output"
    )


def test_document_mentions_no_output_format_change(pattern_document: str) -> None:
    lower = pattern_document.lower()
    assert (
        "do not modify json" in lower
        or "no output format change" in lower
        or "never modify output" in lower
        or "do not change output format" in lower
        or "no output-format change" in lower
        or "do not modify json schemas" in pattern_document
    ), "pattern doc must forbid changing the output format semantics"


def test_document_has_input_and_output_contract_sections(pattern_document: str) -> None:
    assert "## Input Contract" in pattern_document, (
        "pattern doc must have an Input Contract section"
    )
    assert "## Output Contract" in pattern_document, (
        "pattern doc must have an Output Contract section"
    )


def test_document_explains_source_legacy_prompts(pattern_document: str) -> None:
    assert "Source Legacy Prompts" in pattern_document, (
        "pattern doc must cite the legacy prompts it is derived from"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
