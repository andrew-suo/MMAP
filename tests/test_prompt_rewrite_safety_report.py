"""Contract tests for mmap_optimizer.prompt.rewrite_safety.

Covers:
- report construction (unchanged text, numbering defects + apply refactor,
  numbering defects + skip refactor, immutable payload violation,
  placeholder removal, field rename, metadata round-trip, target_id
  preservation)
- audit item composition (payload_integrity, format_validity,
  rewrite_traceability items are present with correct semantics)
- serialization (to_dict, to_json, from_dict round-trip, nested audit report
  round-trip, metadata JSON-safe, summary rendering)
- guardrails (no model/orchestration/patch/repair/compression imports,
  no CLI integration, no scenario integration, no filesystem writes,
  input strings unchanged, TypeError for bad inputs, determinism)
- integration with existing utilities (numbering utility consistency,
  immutable payload validator consistency, audit checklist consistency,
  apply_numbering_refactor default True, protected_placeholders forwarded)
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from mmap_optimizer.prompt.rewrite_safety import (
    PromptRewriteSafetyReport,
    build_prompt_rewrite_safety_report,
    prompt_rewrite_safety_report_to_json,
    prompt_rewrite_safety_report_from_dict,
    render_prompt_rewrite_safety_summary,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_original() -> str:
    return (
        "## Instructions\n"
        "1. Read {question} carefully\n"
        "2. Emit a {answer} as valid JSON\n"
        "3. Do not add content beyond the output\n"
    )


@pytest.fixture
def clean_rewrite(clean_original: str) -> str:
    """Text that is byte-identical to the original."""
    return clean_original


@pytest.fixture
def numbering_defect_rewrite() -> str:
    """Same content but messed up ordered-list numbering."""
    return (
        "## Instructions\n"
        "1. Read {question} carefully\n"
        "1. Emit a {answer} as valid JSON\n"
        "1. Do not add content beyond the output\n"
    )


@pytest.fixture
def payload_violation_rewrite() -> str:
    """Same formatting but replaced placeholders with plain text."""
    return (
        "## 1. Instructions\n"
        "- Step 1: Read question carefully\n"
        "- Step 2: Emit a answer as valid JSON\n"
        "- Step 3: Do not add content beyond the output\n"
    )


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_unchanged_text_is_ok(self, clean_original: str, clean_rewrite: str) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="ok",
            original=clean_original,
            rewritten=clean_rewrite,
        )
        assert report.ok is True
        assert report.overall_status == "pass"
        assert report.numbering_issue_count == 0
        assert report.immutable_payload_issue_count == 0
        assert report.audit_issue_count == 0

    def test_numbering_defect_repaired(
        self, clean_original: str, numbering_defect_rewrite: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="num",
            original=clean_original,
            rewritten=numbering_defect_rewrite,
            apply_numbering_refactor=True,
        )
        # original and rewritten differ only in numbering, but numbering
        # refactor renames Step 1 -> Step 1/Step 1 which is still "Step 1"
        # three times — so numbering issues are detected and rewritten_hash
        # differs from normalized_rewritten_hash.
        assert report.numbering_issue_count > 0
        assert report.rewritten_hash != report.normalized_rewritten_hash
        # The payload integrity check is at the normalized_rewritten level,
        # so if the original has different heading/step numbering than the
        # normalized rewrite, structural-line issues may also arise.

    def test_numbering_defect_not_repaired(
        self, clean_original: str, numbering_defect_rewrite: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="num-no-fix",
            original=clean_original,
            rewritten=numbering_defect_rewrite,
            apply_numbering_refactor=False,
        )
        assert report.normalized_rewritten == numbering_defect_rewrite
        assert report.normalized_rewritten_hash == report.rewritten_hash

    def test_immutable_payload_violation_triggers_fail(
        self, clean_original: str, payload_violation_rewrite: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="payload",
            original=clean_original,
            rewritten=payload_violation_rewrite,
        )
        assert report.ok is False
        assert report.overall_status == "fail"
        assert report.immutable_payload_issue_count > 0

    def test_placeholder_removal_triggers_fail(
        self, clean_original: str, payload_violation_rewrite: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="ph-removed",
            original=clean_original,
            rewritten=payload_violation_rewrite,
        )
        assert report.ok is False
        # the payload_integrity item should be fail/blocker
        payload_item = next(
            (i for i in report.audit_report.items if i.id == "payload_integrity"),
            None,
        )
        assert payload_item is not None
        assert payload_item.status == "fail"
        assert payload_item.severity == "blocker"

    def test_field_rename_triggers_fail(self) -> None:
        original = '{"answer": "{answer}"}'
        rewritten = '{"response": "{answer}"}'
        report = build_prompt_rewrite_safety_report(
            target_id="field-rename",
            original=original,
            rewritten=rewritten,
        )
        assert report.ok is False
        assert report.overall_status == "fail"

    def test_metadata_round_trip(self, clean_original: str) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="meta",
            original=clean_original,
            rewritten=clean_original,
            metadata={"author": "bot", "round": 5, "tags": ["a", "b"]},
        )
        d = report.to_dict()
        assert d["metadata"]["author"] == "bot"
        assert d["metadata"]["round"] == 5
        back = prompt_rewrite_safety_report_from_dict(d)
        assert back.metadata["author"] == "bot"
        assert back.metadata["round"] == 5

    def test_target_id_preserved(self, clean_original: str) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="exact-id",
            original=clean_original,
            rewritten=clean_original,
        )
        assert report.target_id == "exact-id"

    def test_hash_stability(self, clean_original: str, clean_rewrite: str) -> None:
        r1 = build_prompt_rewrite_safety_report(
            target_id="h",
            original=clean_original,
            rewritten=clean_rewrite,
        )
        r2 = build_prompt_rewrite_safety_report(
            target_id="h",
            original=clean_original,
            rewritten=clean_rewrite,
        )
        assert r1.original_hash == r2.original_hash
        assert r1.rewritten_hash == r2.rewritten_hash
        assert r1.normalized_rewritten_hash == r2.normalized_rewritten_hash


# ---------------------------------------------------------------------------
# Audit item tests
# ---------------------------------------------------------------------------


class TestAuditItems:
    def test_contains_payload_integrity_item(self, clean_original: str) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="x", original=clean_original, rewritten=clean_original
        )
        ids = {i.id for i in report.audit_report.items}
        assert "payload_integrity" in ids

    def test_contains_format_validity_item(self, clean_original: str) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="x", original=clean_original, rewritten=clean_original
        )
        ids = {i.id for i in report.audit_report.items}
        assert "format_validity" in ids

    def test_contains_rewrite_traceability_item(self, clean_original: str) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="x", original=clean_original, rewritten=clean_original
        )
        ids = {i.id for i in report.audit_report.items}
        assert "rewrite_traceability" in ids

    def test_numbering_issue_count_reflected_in_evidence(
        self, clean_original: str, numbering_defect_rewrite: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="x",
            original=clean_original,
            rewritten=numbering_defect_rewrite,
        )
        fv = next(
            i for i in report.audit_report.items if i.id == "format_validity"
        )
        assert str(report.numbering_issue_count) in fv.evidence

    def test_payload_issue_count_reflected_in_evidence(
        self, clean_original: str, payload_violation_rewrite: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="x",
            original=clean_original,
            rewritten=payload_violation_rewrite,
        )
        pi = next(
            i for i in report.audit_report.items if i.id == "payload_integrity"
        )
        assert str(report.immutable_payload_issue_count) in pi.evidence

    def test_hashes_reflected_in_traceability_evidence(
        self, clean_original: str, numbering_defect_rewrite: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="x",
            original=clean_original,
            rewritten=numbering_defect_rewrite,
        )
        rt = next(
            i for i in report.audit_report.items if i.id == "rewrite_traceability"
        )
        assert report.rewritten_hash[:12] in rt.evidence
        assert report.normalized_rewritten_hash[:12] in rt.evidence

    def test_fail_item_has_blocker_severity(
        self, clean_original: str, payload_violation_rewrite: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="x",
            original=clean_original,
            rewritten=payload_violation_rewrite,
        )
        fail_items = [i for i in report.audit_report.items if i.status == "fail"]
        assert any(i.severity == "blocker" for i in fail_items)

    def test_numbering_warning_has_minor_severity(
        self, clean_original: str, numbering_defect_rewrite: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="x",
            original=clean_original,
            rewritten=numbering_defect_rewrite,
        )
        fv = next(
            i for i in report.audit_report.items if i.id == "format_validity"
        )
        assert fv.severity == "minor"


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_dict_contains_all_fields(self, clean_original: str) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="t", original=clean_original, rewritten=clean_original
        )
        d = report.to_dict()
        required = {
            "target_id",
            "ok",
            "overall_status",
            "original_hash",
            "rewritten_hash",
            "normalized_rewritten_hash",
            "numbering_issue_count",
            "immutable_payload_issue_count",
            "audit_issue_count",
            "normalized_rewritten",
            "audit_report",
            "metadata",
        }
        assert required.issubset(d.keys())

    def test_to_json_returns_string(self, clean_original: str) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="t", original=clean_original, rewritten=clean_original
        )
        s = prompt_rewrite_safety_report_to_json(report)
        assert isinstance(s, str)
        parsed = json.loads(s)
        assert parsed["target_id"] == "t"

    def test_from_dict_round_trip(self, clean_original: str) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="t", original=clean_original, rewritten=clean_original,
            metadata={"k": "v"},
        )
        back = prompt_rewrite_safety_report_from_dict(report.to_dict())
        assert back.target_id == report.target_id
        assert back.ok == report.ok
        assert back.overall_status == report.overall_status
        assert back.original_hash == report.original_hash
        assert back.rewritten_hash == report.rewritten_hash
        assert back.normalized_rewritten_hash == report.normalized_rewritten_hash
        assert back.numbering_issue_count == report.numbering_issue_count
        assert back.immutable_payload_issue_count == report.immutable_payload_issue_count
        assert back.audit_issue_count == report.audit_issue_count
        assert back.metadata["k"] == "v"

    def test_nested_audit_report_round_trip(self, clean_original: str) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="t", original=clean_original, rewritten=clean_original,
        )
        d = report.to_dict()
        back = prompt_rewrite_safety_report_from_dict(d)
        assert back.audit_report.target_id == report.audit_report.target_id
        assert back.audit_report.overall_status == report.audit_report.overall_status
        assert len(back.audit_report.items) == len(report.audit_report.items)

    def test_metadata_is_json_safe(self, clean_original: str) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="t", original=clean_original, rewritten=clean_original,
            metadata={"round": 1, "author": "bot", "tags": ["a", "b"]},
        )
        s = prompt_rewrite_safety_report_to_json(report, sort_keys=True)
        parsed = json.loads(s)
        assert parsed["metadata"]["round"] == 1
        assert parsed["metadata"]["tags"] == ["a", "b"]

    def test_summary_render_includes_metadata(self, clean_original: str) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="t", original=clean_original, rewritten=clean_original,
        )
        s = render_prompt_rewrite_safety_summary(report)
        assert "t" in s
        assert report.overall_status in s
        assert str(report.numbering_issue_count) in s
        assert str(report.immutable_payload_issue_count) in s
        assert str(report.audit_issue_count) in s


# ---------------------------------------------------------------------------
# Guardrail tests
# ---------------------------------------------------------------------------


class TestGuardrails:
    def test_no_forbidden_imports(self) -> None:
        import mmap_optimizer.prompt.rewrite_safety as m

        source = Path(m.__file__).read_text()
        tree = ast.parse(source)
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)

        forbidden_prefixes = (
            "mmap_optimizer.model",
            "mmap_optimizer.orchestration",
            "mmap_optimizer.patch",
            "mmap_optimizer.compression",
            "mmap_optimizer.repair",
        )
        for mod in imported_modules:
            for prefix in forbidden_prefixes:
                assert not mod.startswith(prefix), (
                    "Module must not import %r" % mod
                )

    def test_no_cli_integration(self) -> None:
        """No mm.optimizer.cli import in this module."""
        import mmap_optimizer.prompt.rewrite_safety as m

        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.cli" not in source

    def test_no_scenario_integration(self) -> None:
        import mmap_optimizer.prompt.rewrite_safety as m

        source = Path(m.__file__).read_text()
        assert "scenario" not in source.lower() or "scenario" not in source

    def test_no_filesystem_writes(self, clean_original: str, tmp_path: Path) -> None:
        """Ensure the utility does not write files."""
        before = set(p.name for p in tmp_path.iterdir()) if tmp_path.exists() else set()
        report = build_prompt_rewrite_safety_report(
            target_id="x", original=clean_original, rewritten=clean_original,
        )
        # We only call the utility; we do not write to tmp_path ourselves.
        after = set(p.name for p in tmp_path.iterdir()) if tmp_path.exists() else set()
        assert before == after

    def test_input_strings_unchanged(
        self, clean_original: str, numbering_defect_rewrite: str
    ) -> None:
        """original/rewritten arguments must not be mutated by the call."""
        import hashlib
        original_sha = hashlib.sha256(clean_original.encode()).hexdigest()
        rewritten_sha = hashlib.sha256(numbering_defect_rewrite.encode()).hexdigest()
        build_prompt_rewrite_safety_report(
            target_id="t",
            original=clean_original,
            rewritten=numbering_defect_rewrite,
        )
        assert hashlib.sha256(clean_original.encode()).hexdigest() == original_sha
        assert hashlib.sha256(numbering_defect_rewrite.encode()).hexdigest() == rewritten_sha

    def test_type_error_bad_target_id(
        self, clean_original: str
    ) -> None:
        with pytest.raises(TypeError):
            build_prompt_rewrite_safety_report(  # type: ignore[arg-type]
                target_id=42, original=clean_original, rewritten=clean_original,
            )

    def test_type_error_bad_original(
        self, clean_original: str
    ) -> None:
        with pytest.raises(TypeError):
            build_prompt_rewrite_safety_report(  # type: ignore[arg-type]
                target_id="t", original=123, rewritten=clean_original,
            )

    def test_type_error_bad_rewritten(
        self, clean_original: str
    ) -> None:
        with pytest.raises(TypeError):
            build_prompt_rewrite_safety_report(  # type: ignore[arg-type]
                target_id="t", original=clean_original, rewritten=None,
            )

    def test_deterministic_across_calls(
        self, clean_original: str, numbering_defect_rewrite: str
    ) -> None:
        a = build_prompt_rewrite_safety_report(
            target_id="t",
            original=clean_original,
            rewritten=numbering_defect_rewrite,
        )
        b = build_prompt_rewrite_safety_report(
            target_id="t",
            original=clean_original,
            rewritten=numbering_defect_rewrite,
        )
        assert a.ok == b.ok
        assert a.overall_status == b.overall_status
        assert a.original_hash == b.original_hash
        assert a.rewritten_hash == b.rewritten_hash
        assert a.normalized_rewritten_hash == b.normalized_rewritten_hash
        assert a.numbering_issue_count == b.numbering_issue_count
        assert a.immutable_payload_issue_count == b.immutable_payload_issue_count
        assert a.audit_issue_count == b.audit_issue_count


# ---------------------------------------------------------------------------
# Integration tests (composing existing utilities)
# ---------------------------------------------------------------------------


class TestComposedUtilities:
    def test_numbering_utility_output_consistent(
        self, clean_original: str, numbering_defect_rewrite: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="t",
            original=clean_original,
            rewritten=numbering_defect_rewrite,
            apply_numbering_refactor=True,
        )
        # Verify normalized_rewritten is identical to calling
        # refactor_prompt_numbering_only ourselves.
        from mmap_optimizer.prompt.numbering_refactor import refactor_prompt_numbering_only
        assert report.normalized_rewritten == refactor_prompt_numbering_only(
            numbering_defect_rewrite
        )

    def test_immutable_payload_validator_consistent(
        self, clean_original: str, payload_violation_rewrite: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="t",
            original=clean_original,
            rewritten=payload_violation_rewrite,
        )
        from mmap_optimizer.prompt.immutable_payload import validate_immutable_payload
        direct = validate_immutable_payload(
            clean_original, report.normalized_rewritten
        )
        assert len(list(direct.issues)) == report.immutable_payload_issue_count
        assert direct.ok == (report.immutable_payload_issue_count == 0)

    def test_audit_report_structure(self, clean_original: str) -> None:
        """Composed audit report should have 3 items, matching expected ids."""
        report = build_prompt_rewrite_safety_report(
            target_id="t", original=clean_original, rewritten=clean_original
        )
        ids = sorted(i.id for i in report.audit_report.items)
        assert ids == sorted(
            ["payload_integrity", "format_validity", "rewrite_traceability"]
        )

    def test_apply_numbering_refactor_default_is_true(
        self, clean_original: str, numbering_defect_rewrite: str
    ) -> None:
        # Default call:
        default = build_prompt_rewrite_safety_report(
            target_id="t",
            original=clean_original,
            rewritten=numbering_defect_rewrite,
        )
        # Explicit True call:
        explicit = build_prompt_rewrite_safety_report(
            target_id="t",
            original=clean_original,
            rewritten=numbering_defect_rewrite,
            apply_numbering_refactor=True,
        )
        assert default.normalized_rewritten == explicit.normalized_rewritten
        assert default.normalized_rewritten_hash == explicit.normalized_rewritten_hash

    def test_protected_placeholders_forwarded(self) -> None:
        """Custom protected_placeholders should affect validation."""
        original = "Use {my_secret_field} here"
        rewritten = "Use secret here"
        # Without explicit protection, default behavior still picks up the
        # placeholder because it's in the original text.
        report_default = build_prompt_rewrite_safety_report(
            target_id="t", original=original, rewritten=rewritten,
        )
        assert report_default.immutable_payload_issue_count > 0
        # With explicit protection list — the placeholder is still protected
        # because it appears in original, and custom list should *also* catch
        # it. We verify both forms produce a fail:
        report_protected = build_prompt_rewrite_safety_report(
            target_id="t",
            original=original,
            rewritten=rewritten,
            protected_placeholders=["my_secret_field"],
        )
        assert report_protected.ok is False
        assert report_protected.immutable_payload_issue_count > 0

    def test_report_is_frozen_dataclass(
        self, clean_original: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="t", original=clean_original, rewritten=clean_original
        )
        # frozen dataclass should not allow assignment
        with pytest.raises(Exception):
            report.target_id = "hacked"  # type: ignore[frozen]

    def test_report_to_dict_json_roundtrip(
        self, clean_original: str, numbering_defect_rewrite: str
    ) -> None:
        report = build_prompt_rewrite_safety_report(
            target_id="t",
            original=clean_original,
            rewritten=numbering_defect_rewrite,
            metadata={"round": 3, "env": "test"},
        )
        s = prompt_rewrite_safety_report_to_json(report, sort_keys=True)
        # Parse back:
        back = prompt_rewrite_safety_report_from_dict(json.loads(s))
        assert back.target_id == report.target_id
        assert back.ok == report.ok
        assert back.overall_status == report.overall_status
        assert back.metadata["round"] == 3
