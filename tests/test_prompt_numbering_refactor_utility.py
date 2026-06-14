"""Contract tests for the numbering-only prompt refactor utility.

These tests only verify the deterministic text-level contract of
:mod:`mmap_optimizer.prompt.numbering_refactor`. They do not invoke a
language model, do not touch the optimizer loop, and do not modify any
default prompt.
"""

from __future__ import annotations

import pytest

from mmap_optimizer.prompt.numbering_refactor import (
    NumberingIssue,
    detect_numbering_issues,
    refactor_markdown_heading_numbering,
    refactor_ordered_list_numbering,
    refactor_prompt_numbering_only,
    refactor_step_numbering,
)


# ---------------------------------------------------------------------------
# Heading tests
# ---------------------------------------------------------------------------


class TestHeadingRenumbering:
    def test_duplicate_heading_numbers_are_sequential(self) -> None:
        source = "## 1. Task\n## 1. Rules\n## 1. Output\n"
        result = refactor_markdown_heading_numbering(source)
        assert result == "## 1. Task\n## 2. Rules\n## 3. Output\n"

    def test_gap_heading_numbers_are_sequential(self) -> None:
        source = "## 1. Task\n## 3. Rules\n## 5. Output\n"
        result = refactor_markdown_heading_numbering(source)
        assert result == "## 1. Task\n## 2. Rules\n## 3. Output\n"

    def test_different_levels_count_independently(self) -> None:
        source = (
            "## 1. Top A\n"
            "### 1. Sub A\n"
            "### 3. Sub B\n"
            "## 2. Top B\n"
            "### 1. Sub C\n"
        )
        result = refactor_markdown_heading_numbering(source)
        assert "## 1. Top A" in result
        assert "## 2. Top B" in result
        assert "### 1. Sub A" in result
        assert "### 2. Sub B" in result
        assert "### 1. Sub C" in result

    def test_sub_heading_numbering_preserves_title_text(self) -> None:
        source = "### 1. First item\n### 1. Second item\n"
        result = refactor_markdown_heading_numbering(source)
        assert "First item" in result
        assert "Second item" in result
        assert "### 1. First item" in result
        assert "### 2. Second item" in result

    def test_non_numeric_headings_are_untouched(self) -> None:
        source = "## Task\n## Rules\n## Output\n"
        assert refactor_markdown_heading_numbering(source) == source

    def test_heading_level_is_preserved(self) -> None:
        source = "# 1. H1\n## 1. H2\n### 1. H3\n"
        result = refactor_markdown_heading_numbering(source)
        lines = result.splitlines()
        assert lines[0].startswith("# ")
        assert lines[1].startswith("## ")
        assert lines[2].startswith("### ")

    def test_heading_body_text_is_untouched(self) -> None:
        source = "## 1. Do not touch this body text\n## 2. Nor this body text\n"
        result = refactor_markdown_heading_numbering(source)
        assert "Do not touch this body text" in result
        assert "Nor this body text" in result

    def test_closing_parenthesis_suffix_is_accepted(self) -> None:
        source = "## 1) Task\n## 1) Rules\n"
        result = refactor_markdown_heading_numbering(source)
        assert result == "## 1) Task\n## 2) Rules\n"


# ---------------------------------------------------------------------------
# Ordered-list tests
# ---------------------------------------------------------------------------


class TestOrderedListRenumbering:
    def test_duplicate_markers_are_sequential(self) -> None:
        source = "1. foo\n1. bar\n1. baz\n"
        assert refactor_ordered_list_numbering(source) == "1. foo\n2. bar\n3. baz\n"

    def test_gap_markers_are_sequential(self) -> None:
        source = "1. foo\n3. bar\n5. baz\n"
        assert refactor_ordered_list_numbering(source) == "1. foo\n2. bar\n3. baz\n"

    def test_indentation_is_preserved(self) -> None:
        source = "1. top\n   1. nested\n   1. nested again\n2. top again\n"
        result = refactor_ordered_list_numbering(source)
        assert result.startswith("1. top\n")
        assert "   1. nested\n" in result
        assert "   2. nested again\n" in result
        assert "2. top again\n" in result

    def test_bullet_lists_are_untouched(self) -> None:
        source = "- a\n- b\n- c\n"
        assert refactor_ordered_list_numbering(source) == source

    def test_plain_prose_is_untouched(self) -> None:
        source = "This is paragraph 1 with a number inside.\nAnother sentence.\n"
        assert refactor_ordered_list_numbering(source) == source

    def test_json_in_prose_is_untouched(self) -> None:
        source = "Only modify markers.\n{\"count\": 3, \"ids\": [1, 2, 3]}\n"
        assert refactor_ordered_list_numbering(source) == source

    def test_closing_parenthesis_suffix_is_accepted(self) -> None:
        source = "1) foo\n1) bar\n"
        assert refactor_ordered_list_numbering(source) == "1) foo\n2) bar\n"


# ---------------------------------------------------------------------------
# Step tests
# ---------------------------------------------------------------------------


class TestStepRenumbering:
    def test_duplicate_step_numbers_are_sequential(self) -> None:
        source = "Step 1: Load data\nStep 1: Validate data\nStep 1: Save data\n"
        expected = "Step 1: Load data\nStep 2: Validate data\nStep 3: Save data\n"
        assert refactor_step_numbering(source) == expected

    def test_gap_step_numbers_are_sequential(self) -> None:
        source = "Step 1: Load data\nStep 3: Validate data\nStep 5: Save data\n"
        expected = "Step 1: Load data\nStep 2: Validate data\nStep 3: Save data\n"
        assert refactor_step_numbering(source) == expected

    def test_step_body_text_is_untouched(self) -> None:
        source = "Step 1: Carefully run model inference\nStep 3: Gather outputs\n"
        result = refactor_step_numbering(source)
        assert "Carefully run model inference" in result
        assert "Gather outputs" in result

    def test_non_step_lines_are_untouched(self) -> None:
        source = "A paragraph with step number 42 and more text.\nStep 1: Real step\n"
        result = refactor_step_numbering(source)
        assert "A paragraph with step number 42" in result
        assert "Step 1: Real step" in result


# ---------------------------------------------------------------------------
# Protection tests
# ---------------------------------------------------------------------------


class TestProtection:
    def test_fenced_code_block_headings_are_untouched(self) -> None:
        source = (
            "## 1. Outside\n"
            "```python\n"
            "## 99. Fake heading inside code\n"
            "1. do something\n"
            "```\n"
            "## 1. Outside again\n"
        )
        result = refactor_prompt_numbering_only(source)
        assert "## 99. Fake heading inside code" in result
        assert "1. do something" in result
        assert "## 1. Outside" in result
        assert "## 2. Outside again" in result

    def test_fenced_json_block_is_untouched(self) -> None:
        source = (
            "Step 1: Generate\n"
            "```json\n"
            "{\"value\": 99, \"items\": [1, 1, 1]}\n"
            "```\n"
            "Step 1: Consume\n"
        )
        result = refactor_prompt_numbering_only(source)
        assert "\"value\": 99" in result
        assert "\"items\": [1, 1, 1]" in result
        assert "Step 2: Consume" in result

    def test_icl_block_is_untouched(self) -> None:
        source = (
            "Step 1: Header\n"
            "=== ICL 示例开始 ===\n"
            "Step 9: Protected step\n"
            "1. bad list number\n"
            "=== ICL 示例结束 ===\n"
            "Step 1: Footer\n"
        )
        result = refactor_prompt_numbering_only(source)
        assert "Step 9: Protected step" in result
        assert "1. bad list number" in result
        assert "Step 2: Footer" in result

    def test_curly_brace_placeholders_are_preserved(self) -> None:
        placeholders = [
            "{question}",
            "{answer}",
            "{label}",
            "{prediction}",
            "{reference}",
            "{context}",
            "{input}",
            "{output}",
        ]
        source = "1. Use {question}\n2. Use {answer}\n" + "".join(
            f"{i + 3}. Keep {p}\n" for i, p in enumerate(placeholders[2:])
        )
        result = refactor_prompt_numbering_only(source)
        for p in placeholders:
            assert p in result

    def test_arbitrary_placeholder_is_preserved(self) -> None:
        source = "1. Hello {custom_placeholder} world\n"
        result = refactor_prompt_numbering_only(source)
        assert "{custom_placeholder}" in result


# ---------------------------------------------------------------------------
# No-logic-alteration tests
# ---------------------------------------------------------------------------


class TestNoLogicAlteration:
    def test_line_count_is_preserved_when_no_additions(self) -> None:
        source = "## 1. Title\n1. item\nStep 1: step\nplain text\n"
        result = refactor_prompt_numbering_only(source)
        assert result.count("\n") == source.count("\n")

    def test_non_number_tokens_are_byte_preserved(self) -> None:
        source = (
            "## 1. Keep this rule exactly as written\n"
            "1. Do not change rule content\n"
            "Step 1: Output schema must remain intact\n"
            "Plain text body line.\n"
        )
        result = refactor_prompt_numbering_only(source)
        for sentence in [
            "Keep this rule exactly as written",
            "Do not change rule content",
            "Output schema must remain intact",
            "Plain text body line.",
        ]:
            assert sentence in result

    def test_no_rules_are_deleted(self) -> None:
        source = "1. Rule A\n2. Rule B\n3. Rule C\n"
        result = refactor_prompt_numbering_only(source)
        for marker in ("Rule A", "Rule B", "Rule C"):
            assert marker in result

    def test_no_rules_are_introduced(self) -> None:
        source = "1. Rule A\n1. Rule B\n"
        result = refactor_prompt_numbering_only(source)
        # The refactor must not append anything to the prompt body.
        assert "Rule A" in result and "Rule B" in result
        assert result.count("\n") == source.count("\n")

    def test_idempotency(self) -> None:
        source = (
            "## 1. Task\n"
            "## 1. Rules\n"
            "## 3. Output\n"
            "1. foo\n"
            "1. bar\n"
            "3. baz\n"
            "Step 1: Load\n"
            "Step 1: Validate\n"
            "Step 3: Save\n"
        )
        first = refactor_prompt_numbering_only(source)
        second = refactor_prompt_numbering_only(first)
        assert first == second


# ---------------------------------------------------------------------------
# Detection API tests
# ---------------------------------------------------------------------------


class TestDetection:
    def test_detects_duplicate_ordered_list(self) -> None:
        source = "1. foo\n1. bar\n3. baz\n"
        issues = detect_numbering_issues(source)
        originals = [i.original for i in issues]
        expected_vals = [i.expected for i in issues]
        assert "1" in originals
        assert "2" in expected_vals

    def test_detects_gap_ordered_list(self) -> None:
        source = "1. foo\n3. bar\n5. baz\n"
        issues = detect_numbering_issues(source)
        assert any(i.original == "3" for i in issues)

    def test_issue_contract_fields(self) -> None:
        source = "## 1. A\n## 1. B\n"
        issues = detect_numbering_issues(source)
        assert issues
        for issue in issues:
            assert isinstance(issue.line_number, int) and issue.line_number > 0
            assert isinstance(issue.original, str) and issue.original.isdigit()
            assert isinstance(issue.expected, str) and issue.expected.isdigit()
            assert isinstance(issue.issue_type, str) and issue.issue_type

    def test_protected_regions_do_not_report_issues(self) -> None:
        source = (
            "Step 1: Outside\n"
            "```python\n"
            "Step 99: Inside code\n"
            "```\n"
            "Step 2: Outside again\n"
        )
        issues = detect_numbering_issues(source)
        # "Step 99" is inside a fence and must not be reported.
        assert not any(i.original == "99" for i in issues)

    def test_clean_prompt_reports_no_issues(self) -> None:
        source = "1. foo\n2. bar\n3. baz\n"
        assert detect_numbering_issues(source) == []


# ---------------------------------------------------------------------------
# Composition API tests
# ---------------------------------------------------------------------------


class TestComposition:
    def test_module_is_importable(self) -> None:
        import mmap_optimizer.prompt.numbering_refactor  # noqa: F401

    def test_composition_runs_all_passes(self) -> None:
        source = (
            "## 1. Task\n"
            "## 1. Rules\n"
            "1. foo\n"
            "1. bar\n"
            "Step 1: Load\n"
            "Step 1: Validate\n"
        )
        result = refactor_prompt_numbering_only(source)
        assert "## 2. Rules" in result
        assert "2. bar" in result
        assert "Step 2: Validate" in result

    def test_rejects_none(self) -> None:
        with pytest.raises((TypeError, ValueError)):
            refactor_prompt_numbering_only(None)  # type: ignore[arg-type]

    def test_rejects_non_string(self) -> None:
        with pytest.raises((TypeError, ValueError)):
            refactor_prompt_numbering_only(1234)  # type: ignore[arg-type]

    def test_empty_string_is_idempotent(self) -> None:
        assert refactor_prompt_numbering_only("") == ""
        assert refactor_prompt_numbering_only("\n") == "\n"
