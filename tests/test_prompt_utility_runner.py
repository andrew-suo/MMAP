"""Contract tests for mmap_optimizer.prompt.utility_runner.

Covers:
- Default behavior (disabled, report_only, no-op)
- Config validation (unknown utility, duplicate, TypeError)
- Utility execution (each utility runs when enabled)
- Report-only guarantees (no mutation, no writes)
- Serialization (to_dict, to_json, from_dict round-trip, summary)
- Failure semantics (ok=False on utility failure)
- Guardrails (no model/orchestration/optimizer/CLI/scenario imports,
  no filesystem writes, no eval/literal_eval, deterministic)
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from mmap_optimizer.prompt.utility_runner import (
    PromptUtilityRunConfig,
    PromptUtilityRunResult,
    SUPPORTED_UTILITIES,
    prompt_utility_run_result_from_dict,
    prompt_utility_run_result_to_json,
    render_prompt_utility_run_summary,
    run_prompt_utilities,
    validate_prompt_utility_run_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_pair() -> tuple[str, str]:
    return (
        "## Instructions\n1. Read {question}\n2. Emit {answer}\n",
        "## Instructions\n1. Read {question}\n2. Emit {answer}\n",
    )


# ---------------------------------------------------------------------------
# Default behavior tests
# ---------------------------------------------------------------------------

class TestDefaultBehavior:
    def test_default_config_disabled(self) -> None:
        config = PromptUtilityRunConfig()
        assert config.enabled is False

    def test_default_report_only(self) -> None:
        config = PromptUtilityRunConfig()
        assert config.report_only is True

    def test_default_ok_true(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(),
        )
        assert result.ok is True

    def test_disabled_config_reports_empty(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(
                enabled=False,
                utilities=("rewrite_safety",),
            ),
        )
        assert result.enabled is False
        assert result.reports == {}
        assert result.ok is True

    def test_disabled_with_warning_issue(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(
                enabled=False,
                utilities=("rewrite_safety",),
            ),
        )
        assert len(result.issues) == 1
        assert "disabled" in result.issues[0]

    def test_original_unchanged(self, simple_pair: tuple[str, str]) -> None:
        original, rewritten = simple_pair
        run_prompt_utilities(
            target_id="t",
            original=original,
            rewritten=rewritten,
            config=PromptUtilityRunConfig(enabled=True, utilities=("rewrite_safety",)),
        )
        # original must not be mutated
        assert original == simple_pair[0]

    def test_rewritten_unchanged(self, simple_pair: tuple[str, str]) -> None:
        original, rewritten = simple_pair
        run_prompt_utilities(
            target_id="t",
            original=original,
            rewritten=rewritten,
            config=PromptUtilityRunConfig(enabled=True, utilities=("rewrite_safety",)),
        )
        # rewritten must not be mutated
        assert rewritten == simple_pair[1]


# ---------------------------------------------------------------------------
# Config validation tests
# ---------------------------------------------------------------------------

class TestConfigValidation:
    def test_unknown_utility_ok_false(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("nonexistent_utility",),
            ),
        )
        assert result.ok is False

    def test_unknown_utility_emits_issue(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("unknown_tool",),
            ),
        )
        assert any("unknown_tool" in i for i in result.issues)

    def test_validate_unknown_utility(self) -> None:
        issues = validate_prompt_utility_run_config(
            PromptUtilityRunConfig(enabled=True, utilities=("bad",))
        )
        assert len(issues) > 0
        assert any("unknown" in i for i in issues)

    def test_validate_duplicate_utility(self) -> None:
        issues = validate_prompt_utility_run_config(
            PromptUtilityRunConfig(
                enabled=True,
                utilities=("rewrite_safety", "rewrite_safety"),
            )
        )
        assert any("duplicate" in i for i in issues)

    def test_validate_empty_ok(self) -> None:
        issues = validate_prompt_utility_run_config(
            PromptUtilityRunConfig(enabled=True, utilities=())
        )
        assert issues == ()

    def test_validate_all_supported_ok(self) -> None:
        all_utilities = tuple(sorted(SUPPORTED_UTILITIES))
        issues = validate_prompt_utility_run_config(
            PromptUtilityRunConfig(
                enabled=True,
                utilities=all_utilities,
                structured_schema={"type": "object"},
            )
        )
        assert issues == ()

    def test_type_error_non_string_target_id(self) -> None:
        with pytest.raises(TypeError):
            run_prompt_utilities(  # type: ignore[arg-type]
                target_id=42,
                original="a",
                rewritten="a",
                config=PromptUtilityRunConfig(),
            )

    def test_type_error_non_string_original(self) -> None:
        with pytest.raises(TypeError):
            run_prompt_utilities(  # type: ignore[arg-type]
                target_id="t",
                original=123,
                rewritten="a",
                config=PromptUtilityRunConfig(),
            )

    def test_type_error_non_string_rewritten(self) -> None:
        with pytest.raises(TypeError):
            run_prompt_utilities(  # type: ignore[arg-type]
                target_id="t",
                original="a",
                rewritten=None,
                config=PromptUtilityRunConfig(),
            )

    def test_type_error_non_config(self) -> None:
        with pytest.raises(TypeError):
            run_prompt_utilities(  # type: ignore[arg-type]
                target_id="t",
                original="a",
                rewritten="a",
                config={"enabled": True},
            )

    def test_type_error_config_bad_enabled(self) -> None:
        with pytest.raises(TypeError):
            PromptUtilityRunConfig(enabled="yes")  # type: ignore[arg-type]

    def test_type_error_config_bad_utilities(self) -> None:
        with pytest.raises(TypeError):
            PromptUtilityRunConfig(enabled=True, utilities="rewrite_safety")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Utility execution tests
# ---------------------------------------------------------------------------

class TestUtilityExecution:
    def test_rewrite_safety_runs(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="## Instructions\n1. Read {q}\n2. Emit {a}\n",
            rewritten="## Instructions\n1. Read {q}\n2. Emit {a}\n",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("rewrite_safety",),
            ),
        )
        assert result.ok is True
        assert "rewrite_safety" in result.reports

    def test_rewrite_safety_honors_apply_json_repair_false(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="## A\n1. Step\n",
            rewritten="## A\n1. Step\n",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("rewrite_safety",),
                apply_json_repair=False,
            ),
        )
        rs = result.reports["rewrite_safety"]
        assert rs.get("json_repair_applied") is False

    def test_rewrite_safety_honors_apply_json_repair_true(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original='{"a":1}',
            rewritten='```json\n{"a":1}\n```',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("rewrite_safety",),
                apply_json_repair=True,
            ),
        )
        rs = result.reports["rewrite_safety"]
        assert rs.get("json_repair_applied") is True
        assert rs.get("json_repair_ok") is True

    def test_json_repair_runs_independently(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten='```json\n{"x":1}\n```',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("json_repair",),
            ),
        )
        assert "json_repair" in result.reports
        assert result.reports["json_repair"]["ok"] is True

    def test_numbering_refactor_runs_independently(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="## Instructions\n1. A\n1. B\n",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("numbering_refactor",),
            ),
        )
        assert "numbering_refactor" in result.reports
        assert result.reports["numbering_refactor"]["issue_count"] > 0

    def test_immutable_payload_runs_independently(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="## Instructions\n1. Read {q}\n2. Emit {a}\n",
            rewritten="## Instructions\n1. Read {q}\n2. Emit {a}\n",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("immutable_payload",),
            ),
        )
        assert "immutable_payload" in result.reports
        assert result.reports["immutable_payload"]["ok"] is True

    def test_audit_checklist_runs(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("audit_checklist",),
            ),
        )
        assert "audit_checklist" in result.reports
        assert result.reports["audit_checklist"]["target_id"] == "t"

    def test_multiple_utilities_run(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="## A\n1. Step\n",
            rewritten="## A\n1. Step\n",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=(
                    "rewrite_safety",
                    "json_repair",
                    "numbering_refactor",
                    "immutable_payload",
                    "audit_checklist",
                ),
            ),
        )
        assert len(result.reports) == 5
        for name in (
            "rewrite_safety",
            "json_repair",
            "numbering_refactor",
            "immutable_payload",
            "audit_checklist",
        ):
            assert name in result.reports


# ---------------------------------------------------------------------------
# Report-only guarantees
# ---------------------------------------------------------------------------

class TestReportOnly:
    def test_json_repair_does_not_mutate_rewritten(self) -> None:
        original_rewritten = '```json\n{"x":1}\n```'
        rewritten = original_rewritten
        run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten=rewritten,
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("json_repair",),
            ),
        )
        assert rewritten == original_rewritten

    def test_numbering_refactor_does_not_mutate_rewritten(self) -> None:
        original_rewritten = "## A\n1. B\n2. C\n"
        rewritten = original_rewritten
        run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten=rewritten,
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("numbering_refactor",),
            ),
        )
        assert rewritten == original_rewritten

    def test_no_filesystem_writes(self, tmp_path: Path) -> None:
        before = set(tmp_path.iterdir()) if tmp_path.exists() else set()
        run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("rewrite_safety",),
            ),
        )
        after = set(tmp_path.iterdir()) if tmp_path.exists() else set()
        assert before == after

    def test_report_only_field_reflected(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("rewrite_safety",),
                report_only=True,
            ),
        )
        assert result.report_only is True


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict_stable(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("rewrite_safety",),
            ),
        )
        d = result.to_dict()
        assert d["target_id"] == "t"
        assert d["ok"] is True
        assert d["enabled"] is True
        assert d["report_only"] is True

    def test_to_json_returns_string(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("rewrite_safety",),
            ),
        )
        s = prompt_utility_run_result_to_json(result)
        assert isinstance(s, str)
        parsed = json.loads(s)
        assert parsed["target_id"] == "t"

    def test_from_dict_round_trip(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("rewrite_safety", "json_repair"),
                metadata={"env": "test"},
            ),
        )
        back = prompt_utility_run_result_from_dict(result.to_dict())
        assert back.target_id == result.target_id
        assert back.enabled == result.enabled
        assert back.report_only == result.report_only
        assert back.utilities == result.utilities
        assert back.ok == result.ok
        assert back.metadata["env"] == "test"

    def test_reports_serializable(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten='```json\n{"x":1}\n```',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("json_repair",),
            ),
        )
        # All nested report values must be JSON-serializable
        s = json.dumps(result.reports)
        assert s  # no error

    def test_summary_includes_target_id(self) -> None:
        result = run_prompt_utilities(
            target_id="my-run",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(enabled=True, utilities=("rewrite_safety",)),
        )
        s = render_prompt_utility_run_summary(result)
        assert "my-run" in s

    def test_summary_includes_enabled(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(enabled=True, utilities=("rewrite_safety",)),
        )
        s = render_prompt_utility_run_summary(result)
        assert "enabled" in s

    def test_summary_includes_ok(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(enabled=True, utilities=("rewrite_safety",)),
        )
        s = render_prompt_utility_run_summary(result)
        assert "ok" in s


# ---------------------------------------------------------------------------
# Failure tests
# ---------------------------------------------------------------------------

class TestFailureSemantics:
    def test_invalid_json_json_repair_requested(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten='{"x":',  # truncated JSON
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("json_repair",),
            ),
        )
        assert result.ok is False
        assert any("ok=False" in i for i in result.issues)

    def test_immutable_payload_violation(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="## A\n1. {x}\n",
            rewritten="## A\n1. changed\n",  # placeholder removed
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("immutable_payload",),
            ),
        )
        assert result.ok is False

    def test_rewrite_safety_failure_propagates(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="## A\n1. {x}\n",
            rewritten="## A\n1. changed\n",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("rewrite_safety",),
            ),
        )
        assert result.ok is False

    def test_disabled_unknown_utility_does_not_fail(self) -> None:
        # When disabled, we don't validate utility names
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(
                enabled=False,
                utilities=("unknown_utility",),
            ),
        )
        # ok=True because runner is disabled
        assert result.ok is True
        assert result.enabled is False

    def test_empty_utilities_with_enabled_ok(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="a",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=(),
            ),
        )
        assert result.ok is True
        assert result.reports == {}


# ---------------------------------------------------------------------------
# Structured schema utility tests
# ---------------------------------------------------------------------------

_SCHEMA = {
    "type": "object",
    "required": ["invoice_id", "amount", "currency"],
    "properties": {
        "invoice_id": {"type": "string"},
        "amount": {"type": "number"},
        "currency": {"type": "string"},
    },
    "additionalProperties": False,
}


class TestStructuredSchemaUtility:
    # ── Config / default tests ──────────────────────────────────────────
    def test_default_config_still_disabled(self) -> None:
        config = PromptUtilityRunConfig()
        assert config.enabled is False
        assert config.structured_schema is None
        assert config.structured_schema_input == "rewritten"

    def test_default_reports_still_empty(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="b",
            config=PromptUtilityRunConfig(),
        )
        assert result.ok is True
        assert result.enabled is False
        assert result.reports == {}

    def test_structured_schema_not_required_unless_requested(self) -> None:
        issues = validate_prompt_utility_run_config(
            PromptUtilityRunConfig(
                enabled=True,
                utilities=("json_repair",),
                structured_schema=None,
            )
        )
        assert issues == ()

    def test_utility_list_includes_structured_schema(self) -> None:
        assert "structured_schema" in SUPPORTED_UTILITIES
        assert "rewrite_safety" in SUPPORTED_UTILITIES
        assert "json_repair" in SUPPORTED_UTILITIES

    def test_unknown_utility_behavior_unchanged(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="b",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("structured_schema", "nonsense"),
                structured_schema=_SCHEMA,
            ),
        )
        assert result.ok is False
        assert any("unknown utility" in i for i in result.issues)

    # ── Success tests ───────────────────────────────────────────────────
    def test_validate_rewritten_json_successfully(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="orig",
            rewritten='{"invoice_id": "INV-1", "amount": 19.99, "currency": "USD"}',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("structured_schema",),
                structured_schema=_SCHEMA,
            ),
        )
        assert result.ok is True
        assert "structured_schema" in result.reports
        assert result.reports["structured_schema"]["ok"] is True
        assert result.reports["structured_schema"]["input"] == "rewritten"

    def test_validate_original_json_successfully(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original='{"invoice_id": "INV-1", "amount": 1, "currency": "USD"}',
            rewritten="irrelevant text",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("structured_schema",),
                structured_schema=_SCHEMA,
                structured_schema_input="original",
            ),
        )
        assert result.ok is True
        assert result.reports["structured_schema"]["input"] == "original"

    def test_validate_json_repair_output_successfully(self) -> None:
        fenced = (
            "```json\n"
            '{"invoice_id": "INV-1", "amount": 1, "currency": "USD"}\n'
            "```"
        )
        result = run_prompt_utilities(
            target_id="t",
            original="orig",
            rewritten=fenced,
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("json_repair", "structured_schema"),
                structured_schema=_SCHEMA,
                structured_schema_input="json_repair",
            ),
        )
        assert result.ok is True
        assert "json_repair" in result.reports
        assert "structured_schema" in result.reports
        assert result.reports["structured_schema"]["input"] == "json_repair"

    def test_structured_schema_report_is_json_serializable(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="orig",
            rewritten='{"invoice_id": "INV-1", "amount": 1, "currency": "USD"}',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("structured_schema",),
                structured_schema=_SCHEMA,
            ),
        )
        dumped = prompt_utility_run_result_to_json(result)
        reloaded = json.loads(dumped)
        assert reloaded["reports"]["structured_schema"]["ok"] is True

    def test_result_ok_true_when_schema_validation_passes(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="orig",
            rewritten='{"invoice_id": "INV-1", "amount": 1, "currency": "USD"}',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("structured_schema",),
                structured_schema=_SCHEMA,
            ),
        )
        assert result.ok is True

    # ── Failure tests ───────────────────────────────────────────────────
    def test_missing_schema_ok_false(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="b",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("structured_schema",),
                structured_schema=None,
            ),
        )
        assert result.ok is False
        assert any(
            "structured_schema" in i and "missing" in i.lower()
            for i in result.issues
        )

    def test_invalid_input_value_ok_false(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten="b",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("structured_schema",),
                structured_schema=_SCHEMA,
                structured_schema_input="bad-value",
            ),
        )
        assert result.ok is False
        assert any(
            "invalid structured_schema_input" in i.lower()
            for i in result.issues
        )

    def test_invalid_json_text_ok_false(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="orig",
            rewritten="not json at all",
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("structured_schema",),
                structured_schema=_SCHEMA,
            ),
        )
        assert result.ok is False
        assert any("structured_schema" in i for i in result.issues)

    def test_schema_validation_failure_ok_false(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="orig",
            rewritten='{"invoice_id": "INV-1"}',  # missing required
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("structured_schema",),
                structured_schema=_SCHEMA,
            ),
        )
        assert result.ok is False
        assert result.reports["structured_schema"]["ok"] is False

    def test_json_repair_not_listed_ok_false(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="orig",
            rewritten='{"invoice_id": "INV-1", "amount": 1, "currency": "USD"}',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("structured_schema",),
                structured_schema=_SCHEMA,
                structured_schema_input="json_repair",
            ),
        )
        assert result.ok is False
        assert any(
            "json_repair input requested" in i.lower() for i in result.issues
        )

    def test_json_repair_failed_ok_false(self) -> None:
        # Force json_repair to fail by giving something very broken
        result = run_prompt_utilities(
            target_id="t",
            original="orig",
            rewritten='{ "truncated": ',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("json_repair", "structured_schema"),
                structured_schema=_SCHEMA,
                structured_schema_input="json_repair",
            ),
        )
        assert result.ok is False
        assert any(
            "json_repair did not produce valid repaired text" in i
            for i in result.issues
        )

    def test_invalid_schema_contract_ok_false(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="orig",
            rewritten='{"invoice_id": "INV-1"}',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("structured_schema",),
                structured_schema={"type": "not_a_real_type"},
            ),
        )
        assert result.ok is False
        assert any("structured_schema" in i for i in result.issues)

    # ── Combined utility tests ──────────────────────────────────────────
    def test_json_repair_plus_structured_schema_ordered(self) -> None:
        fenced = (
            "```json\n"
            '{"invoice_id": "INV-1", "amount": 1, "currency": "USD"}\n'
            "```"
        )
        result = run_prompt_utilities(
            target_id="t",
            original="orig",
            rewritten=fenced,
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("json_repair", "structured_schema"),
                structured_schema=_SCHEMA,
                structured_schema_input="json_repair",
            ),
        )
        assert result.ok is True
        assert "json_repair" in result.reports
        assert "structured_schema" in result.reports

    def test_rewrite_safety_plus_structured_schema_independent(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="## A\n1. {x}\n",
            rewritten='{"invoice_id": "INV-1", "amount": 1, "currency": "USD"}',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("rewrite_safety", "structured_schema"),
                structured_schema=_SCHEMA,
            ),
        )
        assert "rewrite_safety" in result.reports
        assert "structured_schema" in result.reports

    def test_numbering_refactor_plus_structured_schema(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten='{"invoice_id": "INV-1", "amount": 1, "currency": "USD"}',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("numbering_refactor", "structured_schema"),
                structured_schema=_SCHEMA,
            ),
        )
        assert "numbering_refactor" in result.reports
        assert "structured_schema" in result.reports

    def test_immutable_payload_plus_structured_schema(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="orig text",
            rewritten='{"invoice_id": "INV-1", "amount": 1, "currency": "USD"}',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("immutable_payload", "structured_schema"),
                structured_schema=_SCHEMA,
            ),
        )
        assert "immutable_payload" in result.reports
        assert "structured_schema" in result.reports

    def test_audit_checklist_plus_structured_schema(self) -> None:
        result = run_prompt_utilities(
            target_id="t",
            original="a",
            rewritten='{"invoice_id": "INV-1", "amount": 1, "currency": "USD"}',
            config=PromptUtilityRunConfig(
                enabled=True,
                utilities=("audit_checklist", "structured_schema"),
                structured_schema=_SCHEMA,
            ),
        )
        assert "audit_checklist" in result.reports
        assert "structured_schema" in result.reports


# ---------------------------------------------------------------------------
# Guardrail tests
# ---------------------------------------------------------------------------

class TestGuardrails:
    def test_no_llm_imports(self) -> None:
        import mmap_optimizer.prompt.utility_runner as m

        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.model" not in source

    def test_no_orchestration_imports(self) -> None:
        import mmap_optimizer.prompt.utility_runner as m

        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.orchestration" not in source

    def test_no_optimizer_loop_imports(self) -> None:
        import mmap_optimizer.prompt.utility_runner as m

        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.optimizer" not in source

    def test_no_cli_imports(self) -> None:
        import mmap_optimizer.prompt.utility_runner as m

        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.cli" not in source

    def test_no_scenario_imports(self) -> None:
        """Module must not import anything from mmap_optimizer.scenario."""
        import mmap_optimizer.prompt.utility_runner as m

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
        # "scenario" in source is fine (it's in the docstring "scenario-gated")
        # but no mmap_optimizer.scenario import is allowed
        for mod in imported_modules:
            assert not mod.startswith("mmap_optimizer.scenario"), (
                "Module must not import mmap_optimizer.scenario: %r" % mod
            )

    def test_no_patch_integration(self) -> None:
        import mmap_optimizer.prompt.utility_runner as m

        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.patch" not in source

    def test_no_compression_integration(self) -> None:
        import mmap_optimizer.prompt.utility_runner as m

        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.compression" not in source

    def test_no_sampling_integration(self) -> None:
        import mmap_optimizer.prompt.utility_runner as m

        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.sampling" not in source

    def test_no_repair_integration(self) -> None:
        import mmap_optimizer.prompt.utility_runner as m

        source = Path(m.__file__).read_text()
        assert "mmap_optimizer.repair" not in source

    def test_no_eval_or_literal_eval(self) -> None:
        import mmap_optimizer.prompt.utility_runner as m

        source = Path(m.__file__).read_text()
        assert "eval(" not in source
        assert "literal_eval" not in source

    def test_deterministic_across_calls(self) -> None:
        config = PromptUtilityRunConfig(
            enabled=True,
            utilities=("rewrite_safety",),
        )
        a = run_prompt_utilities(
            target_id="t",
            original="## A\n1. Step\n",
            rewritten="## A\n1. Step\n",
            config=config,
        )
        b = run_prompt_utilities(
            target_id="t",
            original="## A\n1. Step\n",
            rewritten="## A\n1. Step\n",
            config=config,
        )
        assert a.ok == b.ok
        assert a.reports == b.reports
        assert a.issues == b.issues
        assert a.enabled == b.enabled
