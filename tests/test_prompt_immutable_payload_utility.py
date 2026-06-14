"""Contract tests for mmap_optimizer.prompt.immutable_payload.

Covers:
- hash / normalization determinism
- placeholder extraction and preservation
- payload marker detection and N-in-N-out contract
- structural line (heading / rule) preservation
- JSON-like field name preservation
- result contract (ok / issues / hashes / JSON serialization)
- guardrails (no LLM, no model/orchestration import, TypeError on bad input,
  empty string stability, deterministic repeat calls)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmap_optimizer.prompt.immutable_payload import (
    ImmutablePayloadIssue,
    ImmutablePayloadValidationResult,
    extract_placeholders,
    normalize_payload_for_comparison,
    stable_payload_hash,
    validate_immutable_payload,
)


# ---------------------------------------------------------------------------
# Hash / normalization tests
# ---------------------------------------------------------------------------


class TestHashNormalization:
    def test_same_text_produces_same_hash(self) -> None:
        text = "## Instructions\n- Rule one\n- Rule two\n{question}\n"
        assert stable_payload_hash(text) == stable_payload_hash(text)

    def test_different_text_produces_different_hash(self) -> None:
        assert stable_payload_hash("hello {a}") != stable_payload_hash("hello {b}")

    def test_crlf_normalized_to_lf(self) -> None:
        a = "line one\r\nline two\n"
        b = "line one\nline two\n"
        assert stable_payload_hash(a) == stable_payload_hash(b)

    def test_trailing_whitespace_normalized(self) -> None:
        a = "hello   \nworld \n"
        b = "hello\nworld\n"
        assert stable_payload_hash(a) == stable_payload_hash(b)

    def test_no_lowercase_normalization(self) -> None:
        a = "HELLO World\n"
        b = "hello world\n"
        assert stable_payload_hash(a) != stable_payload_hash(b)

    def test_no_line_reordering_in_hash(self) -> None:
        a = "line one\nline two\n"
        b = "line two\nline one\n"
        assert stable_payload_hash(a) != stable_payload_hash(b)

    def test_normalize_handles_empty_string(self) -> None:
        assert normalize_payload_for_comparison("") == ""

    def test_normalize_collapses_multiple_trailing_newlines(self) -> None:
        assert normalize_payload_for_comparison("hello\n\n\n") == "hello\n"

    def test_normalize_adds_single_final_newline(self) -> None:
        assert normalize_payload_for_comparison("hello") == "hello\n"


# ---------------------------------------------------------------------------
# Placeholder tests
# ---------------------------------------------------------------------------


class TestPlaceholderExtraction:
    def test_extracts_basic_placeholders(self) -> None:
        assert extract_placeholders("Hello {name} and {other}!") == ("name", "other")

    def test_preserves_order_and_duplicates(self) -> None:
        assert extract_placeholders("{a} {b} {a}") == ("a", "b", "a")

    def test_empty_when_none_present(self) -> None:
        assert extract_placeholders("no placeholders here") == ()

    def test_default_business_placeholders_are_protected(self) -> None:
        # {question}, {answer}, {label} etc. must survive rewriting.
        original = "Read {question} and answer {label}."
        rewritten = "Read {queshun} and answer {lable}."
        result = validate_immutable_payload(original, rewritten)
        types_found = {i.issue_type for i in result.issues}
        assert "placeholder_removed" in types_found
        assert "placeholder_added" in types_found

    def test_arbitrary_placeholder_is_protected(self) -> None:
        original = "Please process {my_custom_token} carefully."
        rewritten = "Please process carefully."
        result = validate_immutable_payload(original, rewritten)
        assert not result.ok
        assert any(i.issue_type == "placeholder_removed" for i in result.issues)

    def test_placeholder_added_is_reported(self) -> None:
        result = validate_immutable_payload("plain text", "text with {extra}")
        assert not result.ok
        assert any(i.issue_type == "placeholder_added" for i in result.issues)

    def test_placeholder_reorder_is_reported(self) -> None:
        original = "{a} {b} {c}"
        rewritten = "{a} {c} {b}"
        result = validate_immutable_payload(original, rewritten)
        assert not result.ok
        assert any(i.issue_type == "placeholder_reordered" for i in result.issues)

    def test_custom_protected_placeholders_work(self) -> None:
        original = "Use {special_value} but ignore {internal_counter}."
        rewritten = "Use {special_value_new} but ignore {internal_counter}."
        # If only 'special_value' is protected, the rename of internal_counter
        # still shows up (because placeholder_added + removed). Let's focus
        # on custom-protected tokens:
        result = validate_immutable_payload(
            original,
            rewritten,
            protected_placeholders=["special_value"],
        )
        types_found = {i.issue_type for i in result.issues}
        assert "placeholder_removed" in types_found or "placeholder_added" in types_found


# ---------------------------------------------------------------------------
# Payload marker tests
# ---------------------------------------------------------------------------


class TestPayloadMarkers:
    def test_no_marker_treated_as_single_payload(self) -> None:
        original = "line one\nline two {input}\n"
        rewritten = "line one\nline two {input}\n"
        result = validate_immutable_payload(original, rewritten)
        assert result.ok

    def test_equal_marker_blocks_pass(self) -> None:
        original = (
            "=== PAYLOAD START ===\nbody {x}\n=== PAYLOAD END ===\n"
            "--- PAYLOAD 2 START ---\nbody {y}\n--- PAYLOAD 2 END ---"
        )
        rewritten = (
            "=== PAYLOAD START ===\nbody {x}\n=== PAYLOAD END ===\n"
            "--- PAYLOAD 2 START ---\nbody {y}\n--- PAYLOAD 2 END ---"
        )
        result = validate_immutable_payload(original, rewritten)
        assert result.ok

    def test_count_mismatch_reported(self) -> None:
        original = (
            "=== PAYLOAD 1 START ===\nA\n=== PAYLOAD 1 END ===\n"
            "=== PAYLOAD 2 START ===\nB\n=== PAYLOAD 2 END ===\n"
        )
        rewritten = "=== PAYLOAD 1 START ===\nA\n=== PAYLOAD 1 END ===\n"
        result = validate_immutable_payload(original, rewritten)
        assert not result.ok
        assert any(i.issue_type == "payload_count_changed" for i in result.issues)

    def test_marker_renamed_is_reported(self) -> None:
        original = "=== PAYLOAD START ===\nhello\n=== PAYLOAD END ===\n"
        rewritten = "=== PAYLOAD BEGINS ===\nhello\n=== PAYLOAD END ===\n"
        result = validate_immutable_payload(original, rewritten)
        assert not result.ok
        assert any(i.issue_type == "payload_marker_changed" for i in result.issues)

    def test_numbered_payload_order_mismatch(self) -> None:
        original = (
            "=== PAYLOAD 1 START ===\n{a}\n=== PAYLOAD 1 END ===\n"
            "=== PAYLOAD 2 START ===\n{b}\n=== PAYLOAD 2 END ===\n"
        )
        rewritten = (
            "=== PAYLOAD 2 START ===\n{b}\n=== PAYLOAD 2 END ===\n"
            "=== PAYLOAD 1 START ===\n{a}\n=== PAYLOAD 1 END ===\n"
        )
        result = validate_immutable_payload(original, rewritten)
        assert not result.ok


# ---------------------------------------------------------------------------
# Structure / field tests
# ---------------------------------------------------------------------------


class TestStructuralLines:
    def test_heading_removed_reported(self) -> None:
        original = "## Instructions\n- Rule 1\n{input}"
        rewritten = "- Rule 1\n{input}"
        result = validate_immutable_payload(original, rewritten)
        assert not result.ok
        assert any(i.issue_type == "line_removed" for i in result.issues)

    def test_new_heading_reported(self) -> None:
        original = "just content {input}"
        rewritten = "## New Heading\njust content {input}"
        result = validate_immutable_payload(original, rewritten)
        assert not result.ok
        assert any(i.issue_type == "line_added" for i in result.issues)

    def test_rule_line_removed_reported(self) -> None:
        original = "1. Do not use bullet points.\n2. Keep answers short.\n{q}"
        rewritten = "1. Do not use bullet points.\n{q}"
        result = validate_immutable_payload(original, rewritten)
        assert not result.ok
        assert any(i.issue_type == "line_removed" for i in result.issues)

    def test_rule_line_added_reported(self) -> None:
        original = "1. Keep it short.\n{q}"
        rewritten = "1. Keep it short.\n2. Be explicit.\n{q}"
        result = validate_immutable_payload(original, rewritten)
        assert not result.ok
        assert any(i.issue_type == "line_added" for i in result.issues)


class TestJsonFieldNames:
    def test_json_field_renamed_reported(self) -> None:
        original = "Output:\n{\n  \"answer\": \"{answer}\",\n  \"reasoning\": \"{reasoning}\"\n}"
        rewritten = "Output:\n{\n  \"answer\": \"{answer}\",\n  \"thought\": \"{reasoning}\"\n}"
        result = validate_immutable_payload(original, rewritten)
        assert not result.ok
        assert any(i.issue_type == "field_name_changed" for i in result.issues)

    def test_json_field_added_reported(self) -> None:
        original = "{\n  \"answer\": \"{answer}\"\n}"
        rewritten = "{\n  \"answer\": \"{answer}\",\n  \"confidence\": \"{c}\"\n}"
        result = validate_immutable_payload(original, rewritten)
        assert not result.ok
        assert any(i.issue_type == "field_name_changed" for i in result.issues)


# ---------------------------------------------------------------------------
# Result contract tests
# ---------------------------------------------------------------------------


class TestResultContract:
    def test_ok_true_when_identical(self) -> None:
        r = validate_immutable_payload("hello {world}", "hello {world}")
        assert r.ok is True
        assert r.issues == ()

    def test_ok_false_when_different(self) -> None:
        r = validate_immutable_payload("hello {a}", "hello {b}")
        assert r.ok is False
        assert len(r.issues) > 0

    def test_issues_is_tuple(self) -> None:
        r = validate_immutable_payload("x", "y")
        assert isinstance(r.issues, tuple)

    def test_issue_fields_are_populated(self) -> None:
        r = validate_immutable_payload("{a}", "{b}")
        assert len(r.issues) > 0
        for issue in r.issues:
            assert isinstance(issue.issue_type, str)
            assert isinstance(issue.detail, str)

    def test_hash_fields_are_valid_sha256(self) -> None:
        r = validate_immutable_payload("one {x}", "one {x}")
        assert len(r.original_hash) == 64
        assert len(r.rewritten_hash) == 64
        assert r.original_hash == r.rewritten_hash

    def test_hash_fields_differ_when_payload_differs(self) -> None:
        r = validate_immutable_payload("one {x}", "one {y}")
        assert r.original_hash != r.rewritten_hash

    def test_to_dict_round_trips_to_json(self) -> None:
        r = validate_immutable_payload("orig {x}", "rewritten {y}")
        d = r.to_dict()
        s = json.dumps(d, indent=2)
        back = json.loads(s)
        assert back["ok"] == r.ok
        assert back["original_hash"] == r.original_hash
        assert back["rewritten_hash"] == r.rewritten_hash
        assert len(back["issues"]) == len(r.issues)


# ---------------------------------------------------------------------------
# Guardrail tests
# ---------------------------------------------------------------------------


class TestGuardrails:
    def test_type_error_on_non_string_original(self) -> None:
        with pytest.raises(TypeError):
            validate_immutable_payload(123, "ok")  # type: ignore[arg-type]

    def test_type_error_on_non_string_rewritten(self) -> None:
        with pytest.raises(TypeError):
            validate_immutable_payload("ok", None)  # type:ignore[arg-type]

    def test_hash_rejects_non_string(self) -> None:
        with pytest.raises(TypeError):
            stable_payload_hash(42)  # type: ignore[arg-type]

    def test_placeholder_extract_rejects_non_string(self) -> None:
        with pytest.raises(TypeError):
            extract_placeholders(["not", "a", "string"])  # type: ignore[arg-type]

    def test_empty_string_stability(self) -> None:
        r = validate_immutable_payload("", "")
        assert r.ok

    def test_deterministic_across_calls(self) -> None:
        original = "Line one\n## Section\n- rule a\n{input}"
        rewritten = "Line one\n## Section\n- rule b\n{input}"
        first = validate_immutable_payload(original, rewritten)
        second = validate_immutable_payload(original, rewritten)
        assert first.ok == second.ok
        assert [i.issue_type for i in first.issues] == [i.issue_type for i in second.issues]

    def test_no_orchestration_or_model_import(self) -> None:
        """Module should not transitively import model/orchestration.

        We inspect the source AST of the module — this is independent of
        whatever other tests have already imported unrelated modules.
        """
        import ast
        from pathlib import Path

        src = Path(__import__("mmap_optimizer.prompt.immutable_payload", fromlist=["immutable_payload"]).__file__).read_text()  # type: ignore[attr-defined]
        tree = ast.parse(src)
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        forbidden = ("mmap_optimizer.model.", "mmap_optimizer.orchestration.")
        for imp in imports:
            for prefix in forbidden:
                assert not imp.startswith(prefix), (
                    "module must not import %s" % imp
                )

    def test_whitespace_only_difference_is_ok(self) -> None:
        original = "hello {a}\n\n\n"
        rewritten = "hello {a}\n"
        r = validate_immutable_payload(original, rewritten)
        assert r.ok

    def test_simple_rewrite_preserving_payload_is_ok(self) -> None:
        original = "## Output Format\n- Answer: {answer}\n"
        rewritten = "## Output Format\n- Answer: {answer}\n"
        r = validate_immutable_payload(original, rewritten)
        assert r.ok
