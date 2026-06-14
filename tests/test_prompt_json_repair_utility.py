"""Contract tests for mmap_optimizer.prompt.json_repair."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from mmap_optimizer.prompt.json_repair import (
    JsonRepairIssue,
    JsonRepairResult,
    ensure_position_valid_json,
    extract_position_valid_json_candidate,
    parse_json_strict,
    repair_json_output,
    strip_json_code_fence,
)


# ---------------------------------------------------------------------------
# Success tests
# ---------------------------------------------------------------------------


class TestSuccess:
    def test_valid_object_json_unchanged(self) -> None:
        text = '{"a": 1, "b": "hello", "c": [1, 2, 3]}'
        result = repair_json_output(text)
        assert result.ok is True
        assert result.parsed == {"a": 1, "b": "hello", "c": [1, 2, 3]}

    def test_valid_array_json_unchanged(self) -> None:
        text = '[1, "x", {"nested": true}]'
        result = repair_json_output(text)
        assert result.ok is True
        assert result.parsed == [1, "x", {"nested": True}]

    def test_fenced_json_stripped(self) -> None:
        text = "```json\n{\"a\": 1}\n```"
        result = repair_json_output(text)
        assert result.ok is True
        assert parse_json_strict(result.repaired_text) == {"a": 1}
        assert any(i.issue_type == "code_fence_removed" for i in result.issues)

    def test_fenced_array_json_stripped(self) -> None:
        text = "```\n[1, 2, 3]\n```"
        result = repair_json_output(text)
        assert result.ok is True
        assert parse_json_strict(result.repaired_text) == [1, 2, 3]

    def test_prefix_suffix_explanation_removed(self) -> None:
        text = "Here is the JSON: {\"answer\": \"yes\"} Thanks."
        result = repair_json_output(text)
        assert result.ok is True
        assert parse_json_strict(result.repaired_text) == {"answer": "yes"}

    def test_wrapping_angle_brackets_repaired(self) -> None:
        text = ">>> {\"a\": 1} <<<"
        result = repair_json_output(text)
        assert result.ok is True
        assert parse_json_strict(result.repaired_text) == {"a": 1}

    def test_object_trailing_comma_repaired(self) -> None:
        result = repair_json_output('{"a": 1,}')
        assert result.ok is True
        assert result.parsed == {"a": 1}
        assert any(i.issue_type == "trailing_comma_removed" for i in result.issues)

    def test_array_trailing_comma_repaired(self) -> None:
        result = repair_json_output("[1, 2,]")
        assert result.ok is True
        assert result.parsed == [1, 2]

    def test_nested_object_trailing_comma_repaired(self) -> None:
        result = repair_json_output('{"outer": {"inner": 1,}}')
        assert result.ok is True
        assert result.parsed == {"outer": {"inner": 1}}

    def test_nested_array_trailing_comma_repaired(self) -> None:
        result = repair_json_output('{"arr": [1, 2,]}')
        assert result.ok is True
        assert result.parsed == {"arr": [1, 2]}

    def test_repaired_text_position_valid(self) -> None:
        for text in [
            '{"a": 1}',
            "[1, 2]",
            "```json\n{\"a\": 1}\n```",
            "Here: {\"a\": 1} thanks.",
            '{"a": 1,}',
            "[1, 2,]",
        ]:
            r = repair_json_output(text)
            assert r.ok
            stripped = r.repaired_text.strip()
            assert stripped.startswith(("{", "["))
            assert stripped.endswith(("}", "]"))

    def test_parsed_value_matches_expected(self) -> None:
        result = repair_json_output('{"x": 42, "s": "hello"}')
        assert result.ok is True
        assert result.parsed["x"] == 42
        assert result.parsed["s"] == "hello"

    def test_non_ascii_preserved(self) -> None:
        result = repair_json_output('{"name": "日本"}')
        assert result.ok is True
        assert result.parsed["name"] == "日本"
        assert "日本" in result.repaired_text


# ---------------------------------------------------------------------------
# Failure tests
# ---------------------------------------------------------------------------


class TestFailure:
    def test_empty_string(self) -> None:
        r = repair_json_output("")
        assert r.ok is False
        assert any(i.issue_type == "empty_input" for i in r.issues)

    def test_whitespace_only(self) -> None:
        r = repair_json_output("   \n\t  ")
        assert r.ok is False

    def test_no_json(self) -> None:
        r = repair_json_output("hello world")
        assert r.ok is False

    def test_only_markdown_without_json(self) -> None:
        r = repair_json_output("```text\nhi\n```")
        assert r.ok is False

    def test_single_quote_dict(self) -> None:
        r = repair_json_output("{'a': 1}")
        assert r.ok is False

    def test_python_true_none(self) -> None:
        r = repair_json_output('{"a": True, "b": None}')
        assert r.ok is False

    def test_bare_key(self) -> None:
        r = repair_json_output("{a: 1}")
        assert r.ok is False

    def test_missing_closing_brace(self) -> None:
        r = repair_json_output('{"a": 1')
        assert r.ok is False

    def test_multiple_ambiguous_json_objects(self) -> None:
        r = repair_json_output('{"a": 1} {"b": 2}')
        assert r.ok is False

    def test_nan(self) -> None:
        r = repair_json_output('{"x": NaN}')
        assert r.ok is False

    def test_infinity(self) -> None:
        r = repair_json_output('{"x": Infinity}')
        assert r.ok is False

    def test_comments_in_json(self) -> None:
        r = repair_json_output('{"a": 1 // comment\n}')
        assert r.ok is False


# ---------------------------------------------------------------------------
# Issue contract tests
# ---------------------------------------------------------------------------


class TestIssueContract:
    def test_code_fence_removed_issue_emitted(self) -> None:
        r = repair_json_output("```json\n{\"a\": 1}\n```")
        assert any(i.issue_type == "code_fence_removed" for i in r.issues)

    def test_exterior_text_removed_issue_emitted(self) -> None:
        r = repair_json_output("Hi {\"a\": 1} Bye.")
        assert any(i.issue_type == "exterior_text_removed" for i in r.issues)

    def test_trailing_comma_removed_issue_emitted(self) -> None:
        r = repair_json_output('{"a": 1,}')
        assert any(i.issue_type == "trailing_comma_removed" for i in r.issues)

    def test_position_invalid_repaired_issue_emitted(self) -> None:
        r = repair_json_output(">>> {\"a\": 1} <<<")
        assert any(i.issue_type == "position_invalid_repaired" for i in r.issues)

    def test_strict_parse_failed_issue_emitted(self) -> None:
        r = repair_json_output('{"broken":')
        assert any(i.issue_type == "strict_parse_failed" for i in r.issues)

    def test_multiple_json_candidates_issue_emitted(self) -> None:
        r = repair_json_output('{"a": 1} {"b": 2}')
        assert any(i.issue_type == "multiple_json_candidates" for i in r.issues)

    def test_unsupported_single_quotes_issue_emitted(self) -> None:
        r = repair_json_output("{'a': 1}")
        assert any(i.issue_type == "unsupported_single_quotes" for i in r.issues)

    def test_unsupported_python_literal_issue_emitted(self) -> None:
        r = repair_json_output('{"a": True}')
        assert any(i.issue_type == "unsupported_python_literal" for i in r.issues)

    def test_unsupported_bare_key_issue_emitted(self) -> None:
        r = repair_json_output("{a: 1}")
        assert any(i.issue_type == "unsupported_bare_key" for i in r.issues)

    def test_empty_input_issue_emitted(self) -> None:
        r = repair_json_output("")
        assert any(i.issue_type == "empty_input" for i in r.issues)

    def test_issue_to_dict_stable(self) -> None:
        issue = JsonRepairIssue(
            issue_type="code_fence_removed",
            detail="Test",
            original_fragment="```json\n{}\n```",
            repaired_fragment="{}",
        )
        d = issue.to_dict()
        assert d["issue_type"] == "code_fence_removed"
        assert issue.to_dict() == d

    def test_result_to_dict_stable(self) -> None:
        r = repair_json_output('{"a": 1}')
        d = r.to_dict()
        assert d["ok"] is True
        assert json.dumps(d)
        assert r.to_dict() == d

    def test_result_json_serialization(self) -> None:
        r = repair_json_output('{"a": 1}')
        d = json.loads(json.dumps(r.to_dict()))
        assert d["ok"] is True


# ---------------------------------------------------------------------------
# Guardrail tests
# ---------------------------------------------------------------------------


class TestGuardrails:
    def test_module_does_not_import_model_or_orchestration(self) -> None:
        import mmap_optimizer.prompt.json_repair as m

        source = Path(m.__file__).read_text()
        tree = ast.parse(source)
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        for imp in imports:
            assert "mmap_optimizer.model" not in imp
            assert "mmap_optimizer.orchestration" not in imp

    def test_module_does_not_import_optimizer_loop(self) -> None:
        import mmap_optimizer.prompt.json_repair as m

        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.optimizer" not in source

    def test_module_does_not_import_patch_or_compression(self) -> None:
        import mmap_optimizer.prompt.json_repair as m

        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.patch" not in source
        assert "mmap_optimizer.compression" not in source

    def test_no_filesystem_writes(self) -> None:
        repair_json_output('{"a": 1}')
        # Pure function — no side effects expected.

    def test_type_error_on_non_string(self) -> None:
        with pytest.raises(TypeError):
            repair_json_output(42)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            parse_json_strict(["a"])  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            strip_json_code_fence(None)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            extract_position_valid_json_candidate(None)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            ensure_position_valid_json(None)  # type: ignore[arg-type]

    def test_deterministic(self) -> None:
        for text in [
            '{"a": 1}',
            "```json\n{\"a\": 1}\n```",
            "Here: {\"x\": true} thanks.",
            '{"a": 1,}',
            "[1, 2,]",
            ">>> {\"a\": 1} <<<",
        ]:
            a = repair_json_output(text)
            b = repair_json_output(text)
            assert a.ok == b.ok
            assert a.repaired_text == b.repaired_text
            assert a.parsed == b.parsed

    def test_no_eval_or_literal_eval_in_source(self) -> None:
        import mmap_optimizer.prompt.json_repair as m

        source = Path(m.__file__).read_text()
        assert "eval(" not in source
        assert "literal_eval" not in source

    def test_does_not_add_unknown_fields(self) -> None:
        text = '{"a": 1}'
        result = repair_json_output(text)
        assert set(result.parsed.keys()) == {"a"}

    def test_does_not_rename_fields(self) -> None:
        text = '{"originalName": 42}'
        result = repair_json_output(text)
        assert "originalName" in result.parsed

    def test_preserves_array_order(self) -> None:
        text = '["first", "second", "third", "fourth"]'
        result = repair_json_output(text)
        assert result.parsed == ["first", "second", "third", "fourth"]

    def test_fence_strip_helper(self) -> None:
        body, issues = strip_json_code_fence("```json\n{\"a\":1}\n```")
        assert any(i.issue_type == "code_fence_removed" for i in issues)
        assert parse_json_strict(body) == {"a": 1}

    def test_candidate_extract_helper(self) -> None:
        body, issues = extract_position_valid_json_candidate(
            "Hi there: {\"x\": 1} Thank you."
        )
        assert parse_json_strict(body) == {"x": 1}

    def test_ensure_position_helper(self) -> None:
        body, issues = ensure_position_valid_json('{"x": 1,}')
        assert parse_json_strict(body) == {"x": 1}
        assert any(i.issue_type == "trailing_comma_removed" for i in issues)
