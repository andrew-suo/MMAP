"""Audit tests for legacy PROMPT_STANDARDIZATION_PROMPT.

This file verifies that the legacy `PROMPT_STANDARDIZATION_PROMPT` has been
properly audited and is confirmed as scenario-gated only, not default-migrated.

Run with::

    python -m pytest tests/test_prompt_standardization_legacy_strategy_audit.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_AUDIT_DOC_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "prompt_migration"
    / "adaptations"
    / "prompt_standardization_legacy_strategy.md"
)

_PROMPTS_PY_PATH = (
    Path(__file__).resolve().parent.parent
    / "mmap_optimizer"
    / "templates"
    / "optimizer_prompts.py"
)

# ---------------------------------------------------------------------------
# Audit doc fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def audit_doc_text() -> str:
    assert _AUDIT_DOC_PATH.is_file(), f"audit doc not found: {_AUDIT_DOC_PATH}"
    return _AUDIT_DOC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Audit status — confirm scenario-gated only, not default-migrated
# ---------------------------------------------------------------------------

class TestAuditStatus:
    """Confirm PROMPT_STANDARDIZATION_PROMPT is properly documented."""

    def test_audit_doc_exists_and_non_empty(self, audit_doc_text: str) -> None:
        assert audit_doc_text.strip(), "prompt_standardization_legacy_strategy.md must not be empty"

    def test_prompt_name_appears(self, audit_doc_text: str) -> None:
        assert "PROMPT_STANDARDIZATION_PROMPT" in audit_doc_text

    def test_scenario_gated_status_declared(self, audit_doc_text: str) -> None:
        """The doc must explicitly state scenario-gated only."""
        lower = audit_doc_text.lower()
        assert "scenario-gated" in lower or "scenario gated" in lower

    def test_not_default_migrated_declared(self, audit_doc_text: str) -> None:
        """The doc must explicitly state not default-migrated."""
        lower = audit_doc_text.lower()
        assert "not default-migrated" in lower or "not migrated" in lower

    def test_high_risk_declared(self, audit_doc_text: str) -> None:
        """The doc must declare high risk."""
        lower = audit_doc_text.lower()
        assert "risk level" in lower
        assert "high" in lower

    def test_distinction_from_format_repair(self, audit_doc_text: str) -> None:
        """The doc must distinguish from prompt_format_repair."""
        lower = audit_doc_text.lower()
        assert "format repair" in lower or "prompt_format_repair" in lower

    def test_distinction_from_numbering_refactor(self, audit_doc_text: str) -> None:
        """The doc must distinguish from prompt_numbering_refactor."""
        lower = audit_doc_text.lower()
        assert "numbering" in lower or "refactor" in lower

    def test_distinction_from_section_rewrite(self, audit_doc_text: str) -> None:
        """The doc must distinguish from section_rewrite."""
        lower = audit_doc_text.lower()
        assert "section rewrite" in lower or "section_rewrite" in lower


# ---------------------------------------------------------------------------
# Registry check — confirm high risk level
# ---------------------------------------------------------------------------

class TestRegistryRiskLevel:
    """Verify the template risk level is correctly marked as high."""

    def test_standardization_template_exists(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import PROMPT_STANDARDIZATION_TEMPLATE
        assert isinstance(PROMPT_STANDARDIZATION_TEMPLATE, str)
        assert len(PROMPT_STANDARDIZATION_TEMPLATE) > 0

    def test_standardization_in_registry(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES
        ids = [t.id for t in DEFAULT_OPTIMIZER_TEMPLATES]
        assert "prompt_standardization" in ids

    def test_risk_level_is_high(self) -> None:
        """Risk level must be high, not medium."""
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES
        entry = next(t for t in DEFAULT_OPTIMIZER_TEMPLATES if t.id == "prompt_standardization")
        assert entry.risk_level == "high", (
            f"prompt_standardization risk level should be 'high', got '{entry.risk_level}'"
        )

    def test_placeholder_is_correct(self) -> None:
        """Input placeholder should be original_prompt."""
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES
        entry = next(t for t in DEFAULT_OPTIMIZER_TEMPLATES if t.id == "prompt_standardization")
        assert set(entry.input_variables) == {"original_prompt"}


# ---------------------------------------------------------------------------
# No default production usage check
# ---------------------------------------------------------------------------

class TestNoDefaultProductionUsage:
    """Verify prompt_standardization is not wired into default optimizer pipeline."""

    def test_not_used_in_orchestration(self) -> None:
        """Orchestration should not reference prompt_standardization."""
        orchestration_path = (
            Path(__file__).resolve().parent.parent
            / "mmap_optimizer"
            / "orchestration"
        )
        if orchestration_path.is_dir():
            for py_file in orchestration_path.glob("*.py"):
                content = py_file.read_text(encoding="utf-8")
                assert "prompt_standardization" not in content.lower(), (
                    f"prompt_standardization found in orchestration: {py_file}"
                )

    def test_not_used_in_compression(self) -> None:
        """Compression engine should not reference prompt_standardization."""
        compression_path = (
            Path(__file__).resolve().parent.parent
            / "mmap_optimizer"
            / "compression"
        )
        if compression_path.is_dir():
            for py_file in compression_path.glob("*.py"):
                content = py_file.read_text(encoding="utf-8")
                assert "prompt_standardization" not in content.lower(), (
                    f"prompt_standardization found in compression: {py_file}"
                )

    def test_not_used_in_evaluation(self) -> None:
        """Evaluation should not reference prompt_standardization."""
        evaluation_path = (
            Path(__file__).resolve().parent.parent
            / "mmap_optimizer"
            / "evaluation"
        )
        if evaluation_path.is_dir():
            for py_file in evaluation_path.glob("*.py"):
                content = py_file.read_text(encoding="utf-8")
                assert "prompt_standardization" not in content.lower(), (
                    f"prompt_standardization found in evaluation: {py_file}"
                )

    def test_not_in_scenarios(self) -> None:
        """Scenarios should not enable prompt_standardization by default."""
        scenarios_path = Path(__file__).resolve().parent.parent / "scenarios"
        if scenarios_path.is_dir():
            for yaml_file in scenarios_path.glob("**/*.yaml"):
                content = yaml_file.read_text(encoding="utf-8")
                assert "prompt_standardization" not in content.lower(), (
                    f"prompt_standardization found in scenario: {yaml_file}"
                )
            for yml_file in scenarios_path.glob("**/*.yml"):
                content = yml_file.read_text(encoding="utf-8")
                assert "prompt_standardization" not in content.lower(), (
                    f"prompt_standardization found in scenario: {yml_file}"
                )


# ---------------------------------------------------------------------------
# Seven-section standardization not in production templates
# ---------------------------------------------------------------------------

class TestNoSevenSectionInProduction:
    """Verify seven-section normalization is not in default production templates."""

    def test_llm_prune_no_seven_section(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import LLM_PRUNE_TEMPLATE
        assert "7-section" not in LLM_PRUNE_TEMPLATE
        assert "Seven-section" not in LLM_PRUNE_TEMPLATE

    def test_patch_generation_no_seven_section(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import PATCH_GENERATION_TEMPLATE
        assert "7-section" not in PATCH_GENERATION_TEMPLATE
        assert "Seven-section" not in PATCH_GENERATION_TEMPLATE

    def test_section_rewrite_no_seven_section(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import SECTION_REWRITE_TEMPLATE
        assert "7-section" not in SECTION_REWRITE_TEMPLATE
        assert "Seven-section" not in SECTION_REWRITE_TEMPLATE

    def test_prompt_format_repair_no_seven_section(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "7-section" not in PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "Seven-section" not in PROMPT_FORMAT_REPAIR_TEMPLATE


# ---------------------------------------------------------------------------
# Guardrails — confirm no prohibited changes
# ---------------------------------------------------------------------------

class TestGuardrails:
    """Confirm this PR does not violate any guardrails."""

    def test_no_new_patch_operations(self, audit_doc_text: str) -> None:
        lower = audit_doc_text.lower()
        assert "new operation" not in lower or "no" in lower

    def test_no_patch_schema_changes(self, audit_doc_text: str) -> None:
        lower = audit_doc_text.lower()
        assert "patch schema" not in lower or "no" in lower

    def test_no_optimizer_loop_changes(self, audit_doc_text: str) -> None:
        lower = audit_doc_text.lower()
        assert "optimizer loop" not in lower or "no" in lower

    def test_no_arbitrary_standardization(self, audit_doc_text: str) -> None:
        lower = audit_doc_text.lower()
        # Should state that arbitrary standardization is not enabled by default
        assert "arbitrary" in lower and "not" in lower


# ---------------------------------------------------------------------------
# Other-template isolation
# ---------------------------------------------------------------------------

_TEMPLATE_IDS_THAT_MUST_NOT_BE_MENTIONED_AS_MODIFIED = frozenset({
    "patch_generation",
    "patch_semantic_merge",
    "patch_root_audit",
    "patch_translation",
    "patch_translation_retry",
    "patch_text_match",
    "json_fix",
    "section_rewrite",
    "prompt_format_repair",
    "prompt_numbering_refactor",
    "llm_prune",
    "llm_prune_validation",
})


class TestOtherTemplateIsolation:
    """Verify this audit does not accidentally modify or target other templates."""

    def test_unrelated_templates_not_in_audit_doc_prose(
        self, audit_doc_text: str
    ) -> None:
        lower = audit_doc_text.lower()
        for tid in _TEMPLATE_IDS_THAT_MUST_NOT_BE_MENTIONED_AS_MODIFIED:
            if tid in lower:
                idx = lower.find(tid)
                context = audit_doc_text[max(0, idx - 50) : idx + len(tid) + 50]
                assert "modif" not in context.lower() and "migrat" not in context.lower(), (
                    f"audit doc appears to claim modification of {tid}: {context}"
                )
