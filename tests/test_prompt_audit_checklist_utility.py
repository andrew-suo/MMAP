"""Contract tests for mmap_optimizer.prompt.audit_checklist.

Covers:
- report construction (dataclass + dict items, status/severity normalization,
  overall_status derivation, failure_summary, repair_recommendation)
- evidence-first validation (pass requires evidence, warning/fail require issue)
- validation rules (empty id/dimension, invalid status/severity, duplicate id,
  empty items, overall_status mismatch, JSON-unsafe metadata)
- serialization (to_dict, to_json, from_dict, round-trip)
- human-readable summary rendering
- read-only guardrail (AST-level import check)
- TypeError / deterministic behaviour
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmap_optimizer.prompt.audit_checklist import (
    AuditChecklistItem,
    AuditChecklistReport,
    build_audit_checklist_report,
    validate_audit_checklist_report,
    audit_checklist_to_json,
    audit_checklist_from_dict,
    render_audit_checklist_summary,
)


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_dataclass_item_builds_report(self) -> None:
        items = [
            AuditChecklistItem(
                id="placeholder-preservation",
                dimension="placeholder_preservation",
                status="pass",
                evidence="All placeholders intact.",
            ),
        ]
        report = build_audit_checklist_report(
            target_id="prompt-v3",
            items=items,
        )
        assert report.target_id == "prompt-v3"
        assert len(report.items) == 1
        assert report.overall_status == "pass"

    def test_dict_item_builds_report(self) -> None:
        items = [
            {
                "id": "schema-preservation",
                "dimension": "output_schema",
                "status": "warning",
                "evidence": "New field added.",
                "issue": "Schema changed unexpectedly.",
                "severity": "minor",
                "suggested_fix": "Revert field addition.",
            },
        ]
        report = build_audit_checklist_report(
            target_id="prompt-v3",
            items=items,
        )
        assert report.overall_status == "warning"
        assert report.items[0].status == "warning"
        assert report.items[0].severity == "minor"

    def test_status_lowercase_normalized(self) -> None:
        items = [
            AuditChecklistItem(id="a", dimension="x", status="PASS",
                               evidence="yes"),
        ]
        report = build_audit_checklist_report(target_id="t", items=items)
        assert report.items[0].status == "pass"

    def test_severity_lowercase_normalized(self) -> None:
        items = [
            AuditChecklistItem(id="a", dimension="x", status="pass",
                               evidence="yes", severity="MAJOR"),
        ]
        report = build_audit_checklist_report(target_id="t", items=items)
        assert report.items[0].severity == "major"

    def test_overall_status_all_pass(self) -> None:
        items = [
            AuditChecklistItem(id="a", dimension="x", status="pass",
                               evidence="yes"),
            AuditChecklistItem(id="b", dimension="y", status="pass",
                               evidence="ok"),
        ]
        report = build_audit_checklist_report(target_id="t", items=items)
        assert report.overall_status == "pass"

    def test_overall_status_any_warning(self) -> None:
        items = [
            AuditChecklistItem(id="a", dimension="x", status="pass",
                               evidence="yes"),
            AuditChecklistItem(id="b", dimension="y", status="warning",
                               evidence="marginal", issue="Close call."),
        ]
        report = build_audit_checklist_report(target_id="t", items=items)
        assert report.overall_status == "warning"

    def test_overall_status_any_fail(self) -> None:
        items = [
            AuditChecklistItem(id="a", dimension="x", status="warning",
                               evidence="marginal", issue="close"),
            AuditChecklistItem(id="b", dimension="y", status="fail",
                               evidence="bad", issue="broken"),
        ]
        report = build_audit_checklist_report(target_id="t", items=items)
        assert report.overall_status == "fail"

    def test_failure_summary_generated(self) -> None:
        items = [
            AuditChecklistItem(
                id="a", dimension="safety", status="fail",
                evidence="none", issue="Missing DO NOT clause.",
                severity="blocker",
            ),
        ]
        report = build_audit_checklist_report(target_id="t", items=items)
        assert report.failure_summary is not None
        assert "safety" in report.failure_summary
        assert "blocker" in report.failure_summary

    def test_repair_recommendation_generated(self) -> None:
        items = [
            AuditChecklistItem(
                id="a", dimension="completeness", status="fail",
                evidence="missing", issue="Rule removed.",
                severity="major",
                suggested_fix="Restore the rule verbatim.",
            ),
        ]
        report = build_audit_checklist_report(target_id="t", items=items)
        assert report.repair_recommendation is not None
        assert "a" in report.repair_recommendation

    def test_input_dict_not_modified(self) -> None:
        raw = {
            "id": "a", "dimension": "x", "status": "pass",
            "evidence": "yes", "severity": "minor",
        }
        build_audit_checklist_report(target_id="t", items=[raw])
        assert raw.get("status") == "pass"
        assert raw.get("severity") == "minor"

    def test_metadata_optional(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="pass", evidence="y")],
        )
        assert report.metadata == {}

    def test_metadata_passed(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="pass", evidence="y")],
            metadata={"author": "bot", "round": 3},
        )
        assert report.metadata["author"] == "bot"
        assert report.metadata["round"] == 3


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestValidation:
    def test_empty_target_id(self) -> None:
        report = build_audit_checklist_report(
            target_id="",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="pass", evidence="y")],
        )
        issues = validate_audit_checklist_report(report)
        assert any("target_id is empty" in i for i in issues)

    def test_empty_items(self) -> None:
        report = AuditChecklistReport(
            target_id="t",
            overall_status="pass",
            items=(),
        )
        issues = validate_audit_checklist_report(report)
        assert any("no items" in i for i in issues)

    def test_empty_item_id(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="", dimension="x",
                                     status="pass", evidence="y")],
        )
        issues = validate_audit_checklist_report(report)
        assert any("empty id" in i for i in issues)

    def test_duplicate_item_id(self) -> None:
        items = [
            AuditChecklistItem(id="a", dimension="x", status="pass",
                               evidence="y"),
            AuditChecklistItem(id="a", dimension="y", status="pass",
                               evidence="y"),
        ]
        report = build_audit_checklist_report(target_id="t", items=items)
        issues = validate_audit_checklist_report(report)
        assert any("duplicate" in i for i in issues)

    def test_empty_dimension(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="", status="pass",
                                     evidence="y")],
        )
        issues = validate_audit_checklist_report(report)
        assert any("empty dimension" in i for i in issues)

    def test_invalid_status(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="maybe", evidence="y")],
        )
        issues = validate_audit_checklist_report(report)
        assert any("invalid status" in i for i in issues)

    def test_invalid_severity(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="pass", evidence="y",
                                     severity="critical")],
        )
        issues = validate_audit_checklist_report(report)
        assert any("invalid severity" in i for i in issues)

    def test_pass_without_evidence(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="pass", evidence="")],
        )
        issues = validate_audit_checklist_report(report)
        assert any("pass" in i and "evidence" in i for i in issues)

    def test_warning_without_issue(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="warning", evidence="y",
                                     issue="")],
        )
        issues = validate_audit_checklist_report(report)
        assert any("warning" in i and "issue" in i for i in issues)

    def test_fail_without_issue(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="fail", evidence="y",
                                     issue="")],
        )
        issues = validate_audit_checklist_report(report)
        assert any("fail" in i and "issue" in i for i in issues)

    def test_overall_status_mismatch(self) -> None:
        # Manually construct a report with mismatched overall_status.
        report = AuditChecklistReport(
            target_id="t",
            overall_status="pass",  # wrong — items contain fail
            items=(
                AuditChecklistItem(id="a", dimension="x", status="fail",
                                   evidence="y", issue="broken"),
            ),
        )
        issues = validate_audit_checklist_report(report)
        assert any("overall_status" in i for i in issues)

    def test_unsafe_metadata(self) -> None:
        report = AuditChecklistReport(
            target_id="t",
            overall_status="pass",
            items=(
                AuditChecklistItem(id="a", dimension="x", status="pass",
                                   evidence="y"),
            ),
            metadata={"bad": object()},
        )
        issues = validate_audit_checklist_report(report)
        assert any("JSON" in i for i in issues)

    def test_valid_report_returns_empty(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[
                AuditChecklistItem(id="a", dimension="x", status="pass",
                                   evidence="yes"),
                AuditChecklistItem(id="b", dimension="y", status="fail",
                                   evidence="n", issue="broken",
                                   suggested_fix="Fix it."),
            ],
        )
        issues = validate_audit_checklist_report(report)
        assert issues == ()


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_item_to_dict_stable(self) -> None:
        item = AuditChecklistItem(
            id="a", dimension="x", status="pass", evidence="y",
            issue=None, severity="info", suggested_fix=None,
        )
        d = item.to_dict()
        assert d["id"] == "a"
        assert d["status"] == "pass"

    def test_report_to_dict_stable(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="pass", evidence="y")],
        )
        d = report.to_dict()
        assert d["target_id"] == "t"
        assert d["overall_status"] == "pass"
        assert isinstance(d["items"], list)

    def test_to_json_string(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="pass", evidence="y")],
        )
        s = audit_checklist_to_json(report)
        parsed = json.loads(s)
        assert parsed["target_id"] == "t"

    def test_to_json_sort_keys_stable(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="pass", evidence="y")],
            metadata={"z": 1, "a": 2},
        )
        s1 = audit_checklist_to_json(report, sort_keys=True)
        s2 = audit_checklist_to_json(report, sort_keys=True)
        assert s1 == s2

    def test_from_dict_round_trip(self) -> None:
        original = build_audit_checklist_report(
            target_id="t",
            items=[
                AuditChecklistItem(id="a", dimension="x", status="fail",
                                   evidence="n", issue="broken",
                                   severity="major",
                                   suggested_fix="Fix."),
            ],
            metadata={"round": 2},
        )
        back = audit_checklist_from_dict(original.to_dict())
        assert back.target_id == original.target_id
        assert back.overall_status == original.overall_status
        assert len(back.items) == len(original.items)
        assert back.items[0].status == "fail"
        assert back.metadata["round"] == 2

    def test_items_is_tuple(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="pass", evidence="y")],
        )
        assert isinstance(report.items, tuple)

    def test_json_round_trip(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[
                AuditChecklistItem(id="a", dimension="x", status="warning",
                                   evidence="close", issue="marginal",
                                   severity="minor"),
            ],
            metadata={"author": "test"},
        )
        s = audit_checklist_to_json(report)
        back = audit_checklist_from_dict(json.loads(s))
        assert back.target_id == report.target_id
        assert back.overall_status == report.overall_status
        assert back.metadata == report.metadata


# ---------------------------------------------------------------------------
# Render tests
# ---------------------------------------------------------------------------

class TestRendering:
    def test_render_contains_target_id(self) -> None:
        report = build_audit_checklist_report(
            target_id="prompt-v42",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="pass", evidence="y")],
        )
        text = render_audit_checklist_summary(report)
        assert "prompt-v42" in text

    def test_render_contains_overall_status(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="fail", evidence="n",
                                     issue="broken")],
        )
        text = render_audit_checklist_summary(report)
        assert "FAIL" in text

    def test_render_contains_counts(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[
                AuditChecklistItem(id="a", dimension="x", status="fail",
                                   evidence="n", issue="x"),
                AuditChecklistItem(id="b", dimension="y", status="warning",
                                   evidence="y", issue="y"),
                AuditChecklistItem(id="c", dimension="z", status="pass",
                                   evidence="z"),
            ],
        )
        text = render_audit_checklist_summary(report)
        assert "fail=1" in text
        assert "warning=1" in text
        assert "pass=1" in text

    def test_render_contains_severity_counts(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[
                AuditChecklistItem(id="a", dimension="x", status="fail",
                                   evidence="n", issue="x", severity="blocker"),
                AuditChecklistItem(id="b", dimension="y", status="fail",
                                   evidence="n", issue="y", severity="major"),
            ],
        )
        text = render_audit_checklist_summary(report)
        assert "blocker=1" in text
        assert "major=1" in text

    def test_render_contains_repair_recommendation(self) -> None:
        report = build_audit_checklist_report(
            target_id="t",
            items=[
                AuditChecklistItem(id="a", dimension="x", status="fail",
                                   evidence="n", issue="x",
                                   suggested_fix="Do this."),
            ],
        )
        text = render_audit_checklist_summary(report)
        assert "REPAIR RECOMMENDATION" in text
        assert "a" in text


# ---------------------------------------------------------------------------
# Guardrail / read-only tests
# ---------------------------------------------------------------------------

class TestGuardrails:
    def test_type_error_on_non_string_target_id(self) -> None:
        with pytest.raises(TypeError):
            build_audit_checklist_report(  # type: ignore[arg-type]
                target_id=42,
                items=[],
            )

    def test_type_error_on_bad_item_type(self) -> None:
        with pytest.raises(TypeError):
            build_audit_checklist_report(  # type: ignore[arg-type]
                target_id="t",
                items=["not-a-dict-or-item"],
            )

    def test_deterministic_across_calls(self) -> None:
        items = [
            AuditChecklistItem(id="a", dimension="x", status="fail",
                               evidence="n", issue="broken"),
        ]
        first = build_audit_checklist_report(target_id="t", items=items)
        second = build_audit_checklist_report(target_id="t", items=items)
        assert first.overall_status == second.overall_status
        assert [i.id for i in first.items] == [i.id for i in second.items]

    def test_empty_metadata_stable(self) -> None:
        r1 = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="pass", evidence="y")],
        )
        r2 = build_audit_checklist_report(
            target_id="t",
            items=[AuditChecklistItem(id="a", dimension="x",
                                     status="pass", evidence="y")],
        )
        assert r1.metadata == r2.metadata == {}

    def test_utility_is_read_only(self) -> None:
        """Module must not transitively import model/orchestration."""
        import ast

        src = Path(
            __import__(
                "mmap_optimizer.prompt.audit_checklist",
                fromlist=["audit_checklist"],
            ).__file__  # type: ignore[attr-defined]
        ).read_text()
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

    def test_from_dict_rejects_non_mapping(self) -> None:
        with pytest.raises(TypeError):
            audit_checklist_from_dict("not a dict")  # type: ignore[arg-type]

    def test_from_dict_rejects_bad_item_list(self) -> None:
        with pytest.raises(ValueError):
            audit_checklist_from_dict({"target_id": "t", "items": "bad"})

    def test_from_dict_rejects_bad_item_element(self) -> None:
        with pytest.raises(ValueError):
            audit_checklist_from_dict({
                "target_id": "t",
                "items": [{"id": "a", "dimension": "x",
                           "status": "pass", "evidence": "y"},
                          42],  # type: ignore[arg-type]
            })
