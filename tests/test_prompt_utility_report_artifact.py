"""Contract tests for mmap_optimizer.prompt.utility_report_artifact.

Covers:
- Build from disabled/enabled runner result
- Field preservation (target_id, ok, enabled, report_only, utilities, issues, reports)
- Metadata merge with explicit metadata winning
- Fixed created_at deterministic
- Hash correctness (original/rewritten/reports/artifact)
- Hash sensitivity to content changes
- artifact_hash self-reference exclusion
- Deterministic same-input hash
- to_dict stability
- to_json parseable
- from_dict round-trip
- tuple/list normalisation
- Nested reports JSON-serialisable
- Non-ASCII metadata preserved
- Validation: valid artifact no issues
- Validation: each field wrong-type / missing
- Validation: hash recomputation mismatch detection
- Guardrails: no model/optimizer/CLI/scenario imports, no writes, deterministic
- Integration: runner -> artifact -> validation
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmap_optimizer.prompt.structured_output_schema import (
    StructuredSchemaValidationResult,
    StructuredSchemaIssue,
)
from mmap_optimizer.prompt.utility_report_artifact import (
    ARTIFACT_TYPE,
    ARTIFACT_VERSION,
    PromptUtilityReportArtifact,
    PromptUtilityReportHashes,
    build_prompt_utility_report_artifact,
    canonicalize_for_report,
    prompt_utility_report_artifact_from_dict,
    prompt_utility_report_artifact_to_json,
    stable_hash,
    validate_prompt_utility_report_artifact,
)
from mmap_optimizer.prompt.utility_runner import (
    PromptUtilityRunConfig,
    PromptUtilityRunResult,
    run_prompt_utilities,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_CREATED_AT = "2026-06-14T00:00:00Z"

_RESULT_DISABLED = PromptUtilityRunResult(
    target_id="t",
    enabled=False,
    report_only=True,
    utilities=(),
    ok=True,
    reports={},
    issues=(),
    metadata={},
)

_RESULT_ENABLED_STRUCTURED_SCHEMA = PromptUtilityRunResult(
    target_id="invoice-v3",
    enabled=True,
    report_only=True,
    utilities=("structured_schema",),
    ok=True,
    reports={
        "structured_schema": {
            "ok": True,
            "issues": [],
            "checked_paths": ["$", "$.invoice_id", "$.amount"],
            "schema_hash": "abc",
            "value_hash": "def",
        }
    },
    issues=(),
    metadata={"scenario": "invoice"},
)

_ORIGINAL_TEXT = "## Invoice Prompt\nPlease process {invoice_id} for {amount} USD."
_REWRITTEN_TEXT = '{"invoice_id": "INV-1", "amount": 19.99, "currency": "USD"}'

_SCHEMA = {
    "type": "object",
    "required": ["invoice_id", "amount"],
    "properties": {
        "invoice_id": {"type": "string"},
        "amount": {"type": "number"},
    },
}


# ---------------------------------------------------------------------------
# Build tests
# ---------------------------------------------------------------------------

class TestBuild:
    def test_build_from_disabled_result(self) -> None:
        artifact = build_prompt_utility_report_artifact(
            result=_RESULT_DISABLED,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        assert artifact.artifact_type == ARTIFACT_TYPE
        assert artifact.artifact_version == ARTIFACT_VERSION
        assert artifact.target_id == "t"
        assert artifact.created_at == _CREATED_AT
        assert artifact.ok is True
        assert artifact.enabled is False
        assert artifact.report_only is True
        assert artifact.utilities == ()
        assert artifact.issues == ()
        assert artifact.reports == {}
        assert isinstance(artifact.hashes, PromptUtilityReportHashes)

    def test_build_from_enabled_result(self) -> None:
        artifact = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        assert artifact.target_id == "invoice-v3"
        assert artifact.ok is True
        assert artifact.enabled is True
        assert artifact.report_only is True
        assert artifact.utilities == ("structured_schema",)

    def test_preserves_ok_enabled_report_only(self) -> None:
        result = PromptUtilityRunResult(
            target_id="t",
            enabled=True,
            report_only=False,
            utilities=("json_repair",),
            ok=False,
            reports={"json_repair": {"ok": False, "issues": []}},
            issues=("json_repair: ok=False",),
            metadata={},
        )
        artifact = build_prompt_utility_report_artifact(
            result=result,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        assert artifact.ok is False
        assert artifact.enabled is True
        assert artifact.report_only is False
        assert artifact.issues == ("json_repair: ok=False",)

    def test_preserves_utilities(self) -> None:
        result = PromptUtilityRunResult(
            target_id="t",
            enabled=True,
            report_only=True,
            utilities=("rewrite_safety", "structured_schema"),
            ok=True,
            reports={"rewrite_safety": {}, "structured_schema": {}},
            issues=(),
            metadata={},
        )
        artifact = build_prompt_utility_report_artifact(
            result=result,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        assert artifact.utilities == ("rewrite_safety", "structured_schema")

    def test_preserves_issues(self) -> None:
        result = PromptUtilityRunResult(
            target_id="t",
            enabled=True,
            report_only=True,
            utilities=("audit_checklist",),
            ok=False,
            reports={},
            issues=("audit_checklist: fail", "some warning"),
            metadata={},
        )
        artifact = build_prompt_utility_report_artifact(
            result=result,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        assert artifact.issues == ("audit_checklist: fail", "some warning")

    def test_preserves_nested_reports(self) -> None:
        artifact = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        assert "structured_schema" in artifact.reports
        ss = artifact.reports["structured_schema"]
        assert ss["ok"] is True
        assert ss["checked_paths"] == ["$", "$.invoice_id", "$.amount"]

    def test_metadata_merge_explicit_wins(self) -> None:
        result = PromptUtilityRunResult(
            target_id="t",
            enabled=True,
            report_only=True,
            utilities=(),
            ok=True,
            reports={},
            issues=(),
            metadata={"scenario": "example", "runner": "v1"},
        )
        artifact = build_prompt_utility_report_artifact(
            result=result,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
            metadata={"scenario": "override", "extra": "field"},
        )
        assert artifact.metadata["scenario"] == "override"
        assert artifact.metadata["runner"] == "v1"
        assert artifact.metadata["extra"] == "field"

    def test_fixed_created_at_deterministic(self) -> None:
        a1 = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        a2 = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        assert a1.created_at == a2.created_at == _CREATED_AT

    def test_created_at_generated_when_none(self) -> None:
        artifact = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
        )
        # Should be non-empty ISO string ending in Z
        assert artifact.created_at.endswith("Z")
        assert len(artifact.created_at) == 20  # YYYY-MM-DDTHH:MM:SSZ


# ---------------------------------------------------------------------------
# Hash tests
# ---------------------------------------------------------------------------

class TestHashes:
    def test_original_hash_changes_on_original_change(self) -> None:
        a1 = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original="A",
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        a2 = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original="B",
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        assert a1.hashes.original_hash != a2.hashes.original_hash

    def test_rewritten_hash_changes_on_rewritten_change(self) -> None:
        a1 = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten='{"a":1}',
            created_at=_CREATED_AT,
        )
        a2 = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten='{"a":2}',
            created_at=_CREATED_AT,
        )
        assert a1.hashes.rewritten_hash != a2.hashes.rewritten_hash

    def test_reports_hash_changes_on_reports_change(self) -> None:
        r1 = PromptUtilityRunResult(
            target_id="t",
            enabled=True,
            report_only=True,
            utilities=("json_repair",),
            ok=True,
            reports={"json_repair": {"ok": True}},
            issues=(),
            metadata={},
        )
        r2 = PromptUtilityRunResult(
            target_id="t",
            enabled=True,
            report_only=True,
            utilities=("json_repair",),
            ok=False,
            reports={"json_repair": {"ok": False}},
            issues=(),
            metadata={},
        )
        a1 = build_prompt_utility_report_artifact(
            result=r1, original="x", rewritten="y", created_at=_CREATED_AT,
        )
        a2 = build_prompt_utility_report_artifact(
            result=r2, original="x", rewritten="y", created_at=_CREATED_AT,
        )
        assert a1.hashes.reports_hash != a2.hashes.reports_hash

    def test_artifact_hash_changes_when_artifact_content_changes(self) -> None:
        a1 = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        a2 = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original="changed original",
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        assert a1.hashes.artifact_hash != a2.hashes.artifact_hash

    def test_artifact_hash_does_not_include_itself(self) -> None:
        """artifact_hash must not embed its own value."""
        artifact = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        # The hash must not contain the hex string of the hash itself
        body_without_hash = canonicalize_for_report({
            k: v for k, v in artifact.to_dict().items() if k != "hashes"
        })
        body_without_hash["hashes"] = {
            k: v
            for k, v in artifact.to_dict()["hashes"].items()
            if k != "artifact_hash"
        }
        expected = stable_hash(body_without_hash)
        assert artifact.hashes.artifact_hash == expected

    def test_same_input_produces_same_hash(self) -> None:
        a1 = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        a2 = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        assert a1.hashes.artifact_hash == a2.hashes.artifact_hash
        assert a1.hashes.original_hash == a2.hashes.original_hash
        assert a1.hashes.rewritten_hash == a2.hashes.rewritten_hash
        assert a1.hashes.reports_hash == a2.hashes.reports_hash


# ---------------------------------------------------------------------------
# Serialisation tests
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict_stable(self) -> None:
        artifact = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        d1 = artifact.to_dict()
        d2 = artifact.to_dict()
        assert d1 == d2

    def test_to_json_parseable(self) -> None:
        artifact = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        s = prompt_utility_report_artifact_to_json(artifact)
        parsed = json.loads(s)
        assert parsed["artifact_type"] == ARTIFACT_TYPE
        assert parsed["ok"] is True

    def test_from_dict_roundtrip(self) -> None:
        artifact = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        reconstructed = prompt_utility_report_artifact_from_dict(
            artifact.to_dict()
        )
        assert reconstructed.to_dict() == artifact.to_dict()

    def test_tuple_list_normalization_stable(self) -> None:
        # Simulate a dict that uses tuples instead of lists (as dataclass.to_dict returns)
        artifact = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        d = artifact.to_dict()
        # Change utilities from list to tuple (simulate dataclass output)
        d["utilities"] = tuple(d["utilities"])
        d["issues"] = tuple(d["issues"])
        reloaded = prompt_utility_report_artifact_from_dict(d)
        assert reloaded.utilities == artifact.utilities
        assert reloaded.issues == artifact.issues

    def test_nested_reports_json_serializable(self) -> None:
        artifact = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        s = json.dumps(artifact.reports)
        assert isinstance(s, str)

    def test_non_ascii_metadata_preserved(self) -> None:
        result = PromptUtilityRunResult(
            target_id="t",
            enabled=True,
            report_only=True,
            utilities=(),
            ok=True,
            reports={},
            issues=(),
            metadata={},
        )
        artifact = build_prompt_utility_report_artifact(
            result=result,
            original="中文原文",
            rewritten="日本語書き",
            created_at=_CREATED_AT,
            metadata={"note": "日本語と中文"},
        )
        s = prompt_utility_report_artifact_to_json(artifact)
        parsed = json.loads(s)
        assert parsed["metadata"]["note"] == "日本語と中文"
        # original_hash lives inside the hashes dict
        assert "hashes" in parsed
        assert "original_hash" in parsed["hashes"]


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestValidation:
    def _valid_artifact(self) -> dict[str, Any]:
        artifact = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        return artifact.to_dict()

    # ── Valid artifact ───────────────────────────────────────────────────
    def test_valid_artifact_has_no_issues(self) -> None:
        artifact = build_prompt_utility_report_artifact(
            result=_RESULT_ENABLED_STRUCTURED_SCHEMA,
            original=_ORIGINAL_TEXT,
            rewritten=_REWRITTEN_TEXT,
            created_at=_CREATED_AT,
        )
        assert validate_prompt_utility_report_artifact(artifact) == ()

    def test_valid_dict_artifact_has_no_issues(self) -> None:
        d = self._valid_artifact()
        assert validate_prompt_utility_report_artifact(d) == ()

    # ── artifact_type ──────────────────────────────────────────────────
    def test_invalid_artifact_type_issue(self) -> None:
        d = self._valid_artifact()
        d["artifact_type"] = "wrong_type"
        issues = validate_prompt_utility_report_artifact(d)
        assert any("artifact_type" in i for i in issues)

    def test_missing_artifact_type_issue(self) -> None:
        d = self._valid_artifact()
        del d["artifact_type"]
        issues = validate_prompt_utility_report_artifact(d)
        assert any("artifact_type" in i for i in issues)

    # ── artifact_version ────────────────────────────────────────────────
    def test_invalid_artifact_version_issue(self) -> None:
        d = self._valid_artifact()
        d["artifact_version"] = "99.99"
        issues = validate_prompt_utility_report_artifact(d)
        assert any("artifact_version" in i for i in issues)

    def test_missing_artifact_version_issue(self) -> None:
        d = self._valid_artifact()
        del d["artifact_version"]
        issues = validate_prompt_utility_report_artifact(d)
        assert any("artifact_version" in i for i in issues)

    # ── target_id ──────────────────────────────────────────────────────
    def test_missing_target_id_issue(self) -> None:
        d = self._valid_artifact()
        del d["target_id"]
        issues = validate_prompt_utility_report_artifact(d)
        assert any("target_id" in i for i in issues)

    def test_empty_target_id_issue(self) -> None:
        d = self._valid_artifact()
        d["target_id"] = ""
        issues = validate_prompt_utility_report_artifact(d)
        assert any("target_id" in i for i in issues)

    # ── ok ──────────────────────────────────────────────────────────────
    def test_bad_ok_type_issue(self) -> None:
        d = self._valid_artifact()
        d["ok"] = "true"  # type: ignore
        issues = validate_prompt_utility_report_artifact(d)
        assert any('ok must be bool' in i for i in issues)

    # ── enabled ───────────────────────────────────────────────────────
    def test_bad_enabled_type_issue(self) -> None:
        d = self._valid_artifact()
        d["enabled"] = 1  # type: ignore
        issues = validate_prompt_utility_report_artifact(d)
        assert any('enabled must be bool' in i for i in issues)

    # ── report_only ────────────────────────────────────────────────────
    def test_bad_report_only_type_issue(self) -> None:
        d = self._valid_artifact()
        d["report_only"] = "yes"  # type: ignore
        issues = validate_prompt_utility_report_artifact(d)
        assert any('report_only must be bool' in i for i in issues)

    # ── utilities ─────────────────────────────────────────────────────
    def test_bad_utilities_type_issue(self) -> None:
        d = self._valid_artifact()
        d["utilities"] = "json_repair"  # type: ignore
        issues = validate_prompt_utility_report_artifact(d)
        assert any('utilities must be' in i for i in issues)

    def test_missing_utilities_issue(self) -> None:
        d = self._valid_artifact()
        del d["utilities"]
        issues = validate_prompt_utility_report_artifact(d)
        assert any("utilities" in i for i in issues)

    # ── issues ─────────────────────────────────────────────────────────
    def test_bad_issues_type_issue(self) -> None:
        d = self._valid_artifact()
        d["issues"] = {"a": "b"}  # type: ignore
        issues = validate_prompt_utility_report_artifact(d)
        assert any('issues must be' in i for i in issues)

    def test_missing_issues_issue(self) -> None:
        d = self._valid_artifact()
        del d["issues"]
        issues = validate_prompt_utility_report_artifact(d)
        assert any("issues" in i for i in issues)

    # ── reports ────────────────────────────────────────────────────────
    def test_bad_reports_type_issue(self) -> None:
        d = self._valid_artifact()
        d["reports"] = "not a dict"  # type: ignore
        issues = validate_prompt_utility_report_artifact(d)
        assert any("reports must be dict-like" in i for i in issues)

    def test_missing_reports_issue(self) -> None:
        d = self._valid_artifact()
        del d["reports"]
        issues = validate_prompt_utility_report_artifact(d)
        assert any("reports" in i for i in issues)

    # ── metadata ───────────────────────────────────────────────────────
    def test_bad_metadata_type_issue(self) -> None:
        d = self._valid_artifact()
        d["metadata"] = ["a", "b"]  # type: ignore
        issues = validate_prompt_utility_report_artifact(d)
        assert any("metadata must be dict-like" in i for i in issues)

    def test_missing_metadata_issue(self) -> None:
        d = self._valid_artifact()
        del d["metadata"]
        issues = validate_prompt_utility_report_artifact(d)
        assert any("metadata" in i for i in issues)

    # ── hashes ────────────────────────────────────────────────────────
    def test_missing_hash_key_issue(self) -> None:
        d = self._valid_artifact()
        del d["hashes"]["artifact_hash"]
        issues = validate_prompt_utility_report_artifact(d)
        assert any("artifact_hash" in i for i in issues)

    def test_bad_reports_hash_issue(self) -> None:
        d = self._valid_artifact()
        d["hashes"]["reports_hash"] = "0000000000000000000000000000000000000000000000000000000000000000"
        issues = validate_prompt_utility_report_artifact(d)
        assert any("reports_hash mismatch" in i for i in issues)

    def test_bad_artifact_hash_issue(self) -> None:
        d = self._valid_artifact()
        d["hashes"]["artifact_hash"] = "0000000000000000000000000000000000000000000000000000000000000000"
        issues = validate_prompt_utility_report_artifact(d)
        assert any("artifact_hash mismatch" in i for i in issues)

    def test_non_dict_artifact_returns_type_issue(self) -> None:
        issues = validate_prompt_utility_report_artifact("not a dict")  # type: ignore
        assert len(issues) == 1
        assert "dict-like" in issues[0]

    # ── created_at ─────────────────────────────────────────────────────
    def test_missing_created_at_issue(self) -> None:
        d = self._valid_artifact()
        del d["created_at"]
        issues = validate_prompt_utility_report_artifact(d)
        assert any("created_at" in i for i in issues)

    def test_empty_created_at_issue(self) -> None:
        d = self._valid_artifact()
        d["created_at"] = ""
        issues = validate_prompt_utility_report_artifact(d)
        assert any("created_at" in i for i in issues)

    # ── enabled field ──────────────────────────────────────────────────
    def test_missing_enabled_issue(self) -> None:
        d = self._valid_artifact()
        del d["enabled"]
        issues = validate_prompt_utility_report_artifact(d)
        assert any("enabled" in i for i in issues)


# ---------------------------------------------------------------------------
# Guardrail tests
# ---------------------------------------------------------------------------

class TestGuardrails:
    def test_no_llm_imports(self) -> None:
        import mmap_optimizer.prompt.utility_report_artifact as m
        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.model" not in source

    def test_no_orchestration_imports(self) -> None:
        import mmap_optimizer.prompt.utility_report_artifact as m
        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.orchestration" not in source

    def test_no_optimizer_loop_imports(self) -> None:
        import mmap_optimizer.prompt.utility_report_artifact as m
        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.optimizer" not in source

    def test_no_cli_imports(self) -> None:
        import mmap_optimizer.prompt.utility_report_artifact as m
        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.cli" not in source

    def test_no_scenario_imports(self) -> None:
        import mmap_optimizer.prompt.utility_report_artifact as m
        source = Path(m.__file__).read_text()
        # The word "scenario" appears in docstrings / design rationale only;
        # it must not appear as a module import path.
        assert "scenario" not in source or "scenario" not in source.split("scenario")[0][-50:]

    def test_no_eval(self) -> None:
        import mmap_optimizer.prompt.utility_report_artifact as m
        source = Path(m.__file__).read_text()
        assert "eval(" not in source
        assert "ast.literal_eval" not in source

    def test_deterministic_hash(self) -> None:
        h1 = stable_hash({"a": 1, "b": 2})
        h2 = stable_hash({"a": 1, "b": 2})
        assert h1 == h2

    def test_canonicalize_tuples_to_lists(self) -> None:
        inp = {"u": (1, 2), "v": {"x": ("a",), "y": 1}}
        out = canonicalize_for_report(inp)
        assert isinstance(out["u"], list)
        assert isinstance(out["v"]["x"], list)
        assert out == {"u": [1, 2], "v": {"x": ["a"], "y": 1}}


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_runner_disabled_result_to_artifact_to_validation(self) -> None:
        result = run_prompt_utilities(
            target_id="integration-t",
            original="original text",
            rewritten="rewritten text",
            config=PromptUtilityRunConfig(),
        )
        artifact = build_prompt_utility_report_artifact(
            result=result,
            original="original text",
            rewritten="rewritten text",
            created_at=_CREATED_AT,
        )
        issues = validate_prompt_utility_report_artifact(artifact)
        assert issues == ()
        assert artifact.enabled is False
        assert artifact.ok is True

    def test_runner_with_structured_schema_to_artifact(self) -> None:
        result = run_prompt_utilities(
            target_id="integration-structured",
            original=_ORIGINAL_TEXT,
            rewritten='{"invoice_id": "INV-1", "amount": 19.99}',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("structured_schema",),
                structured_schema=_SCHEMA,
            ),
        )
        artifact = build_prompt_utility_report_artifact(
            result=result,
            original=_ORIGINAL_TEXT,
            rewritten='{"invoice_id": "INV-1", "amount": 19.99}',
            created_at=_CREATED_AT,
        )
        issues = validate_prompt_utility_report_artifact(artifact)
        assert issues == ()
        assert artifact.ok is True
        assert "structured_schema" in artifact.reports

    def test_runner_json_repair_plus_structured_schema_to_artifact(self) -> None:
        result = run_prompt_utilities(
            target_id="integration-combined",
            original="orig",
            rewritten='```json\n{"invoice_id": "INV-1", "amount": 19.99}\n```',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("json_repair", "structured_schema"),
                structured_schema=_SCHEMA,
                structured_schema_input="json_repair",
            ),
        )
        artifact = build_prompt_utility_report_artifact(
            result=result,
            original="orig",
            rewritten='```json\n{"invoice_id": "INV-1", "amount": 19.99}\n```',
            created_at=_CREATED_AT,
        )
        issues = validate_prompt_utility_report_artifact(artifact)
        assert issues == ()
        assert artifact.ok is True
        assert "json_repair" in artifact.reports
        assert "structured_schema" in artifact.reports

    def test_artifact_json_roundtrip_via_json_module(self) -> None:
        result = run_prompt_utilities(
            target_id="roundtrip",
            original="original",
            rewritten='{"a": 1}',
            config=PromptUtilityRunConfig(enabled=True, utilities=()),
        )
        artifact = build_prompt_utility_report_artifact(
            result=result,
            original="original",
            rewritten='{"a": 1}',
            created_at=_CREATED_AT,
        )
        s = prompt_utility_report_artifact_to_json(artifact)
        parsed = json.loads(s)
        reloaded = prompt_utility_report_artifact_from_dict(parsed)
        assert reloaded.to_dict() == artifact.to_dict()
        assert validate_prompt_utility_report_artifact(reloaded) == ()
