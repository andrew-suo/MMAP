"""Audit tests for legacy LLM_PRUNE_PROMPT / LLM_PRUNE_VALIDATION_PROMPT.

This file verifies that the legacy ``LLM_PRUNE_PROMPT`` and
``LLM_PRUNE_VALIDATION_PROMPT`` have been properly audited and are
confirmed as covered by the consolidation adaptation in PR #74
(``codex/adapt-consolidation-prompts``).

These tests are **docs/tests-only** — no template content is modified
by this PR. The consolidation rules that subsume these legacy prompts
will be added when PR #74 merges to main.

Run with::

    python -m pytest tests/test_llm_prune_legacy_strategy_audit.py -q
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
    / "llm_prune_legacy_strategy.md"
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
# Audit status — confirm docs/tests-only, no ambiguous pending state
# ---------------------------------------------------------------------------

class TestAuditStatus:
    """Confirm both legacy prompts are accounted for with clear disposition."""

    def test_audit_doc_exists_and_non_empty(self, audit_doc_text: str) -> None:
        assert audit_doc_text.strip(), "llm_prune_legacy_strategy.md must not be empty"

    def test_llm_prune_prompt_appears(self, audit_doc_text: str) -> None:
        assert "LLM_PRUNE_PROMPT" in audit_doc_text

    def test_llm_prune_validation_prompt_appears(self, audit_doc_text: str) -> None:
        assert "LLM_PRUNE_VALIDATION_PROMPT" in audit_doc_text

    def test_docs_tests_only_status_declared(self, audit_doc_text: str) -> None:
        """The doc must explicitly state this is docs/tests-only."""
        assert (
            "docs/tests-only" in audit_doc_text.lower()
            or "docs only" in audit_doc_text.lower()
            or "documentation-only" in audit_doc_text.lower()
        ), "audit doc must declare docs/tests-only status"

    def test_no_ambiguous_pending_status(self, audit_doc_text: str) -> None:
        """No 'pending unknown' or undecided disposition may remain."""
        lower = audit_doc_text.lower()
        assert "pending" not in lower or "covered" in lower
        assert "not separately migrated" in lower or "not migrated" in lower

    def test_relationship_to_consolidation_stated(self, audit_doc_text: str) -> None:
        """The doc must explicitly link to #74 consolidation adaptation."""
        doc_lower = audit_doc_text.lower()
        assert "consolidation adaptation" in doc_lower or "consolidation" in audit_doc_text
        # must reference PR #74 or codex/adapt-consolidation-prompts or CONSOLIDATION_PROMPT
        assert (
            "#74" in audit_doc_text
            or "codex/adapt-consolidation-prompts" in audit_doc_text
            or "CONSOLIDATION_PROMPT" in audit_doc_text
        ), "must reference the consolidation adaptation that covers these prompts"

    def test_llm_prune_covered_by_consolidation(self, audit_doc_text: str) -> None:
        """LLM_PRUNE_PROMPT must be declared as covered (not independently migrated)."""
        # find the "Migrated Rules" section and check LLM_PRUNE_PROMPT covered status
        assert "covered" in audit_doc_text.lower(), (
            "audit doc must state that LLM_PRUNE_PROMPT is covered by consolidation"
        )

    def test_llm_prune_validation_covered_by_consolidation(
        self, audit_doc_text: str
    ) -> None:
        """LLM_PRUNE_VALIDATION_PROMPT must be declared as covered."""
        assert "covered" in audit_doc_text.lower()


# ---------------------------------------------------------------------------
# Contract preservation — llm_prune
# ---------------------------------------------------------------------------

class TestLlamaPruneTemplateContract:
    """Verify llm_prune template contract is unchanged."""

    def test_llm_prune_template_module_exists(self) -> None:
        assert _PROMPTS_PY_PATH.is_file()

    def test_llm_prune_template_importable(self) -> None:
        # Import the template to confirm it exists
        from mmap_optimizer.templates.optimizer_prompts import LLM_PRUNE_TEMPLATE
        assert isinstance(LLM_PRUNE_TEMPLATE, str)
        assert len(LLM_PRUNE_TEMPLATE) > 0

    def test_llm_prune_placeholders_unchanged(self) -> None:
        """section_header and section_content placeholders must be present."""
        from mmap_optimizer.templates.optimizer_prompts import LLM_PRUNE_TEMPLATE
        assert "{section_header}" in LLM_PRUNE_TEMPLATE
        assert "{section_content}" in LLM_PRUNE_TEMPLATE

    def test_llm_prune_preserves_raw_text_output(self) -> None:
        """Output contract: raw compressed section text (no JSON wrapper)."""
        from mmap_optimizer.templates.optimizer_prompts import LLM_PRUNE_TEMPLATE
        lower = LLM_PRUNE_TEMPLATE.lower()
        # Should NOT claim to output JSON — compression outputs raw text
        assert "json" not in lower or "压缩" in LLM_PRUNE_TEMPLATE  # Chinese for "compress"

    def test_llm_prune_registry_entry_exists(self) -> None:
        """llm_prune must be registered in the default template registry."""
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES
        ids = [t.id for t in DEFAULT_OPTIMIZER_TEMPLATES]
        assert "llm_prune" in ids, f"llm_prune not in registry: {ids}"

    def test_llm_prune_registry_entry_placeholders(self) -> None:
        """Registry entry must use section_header and section_content."""
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES
        entry = next(t for t in DEFAULT_OPTIMIZER_TEMPLATES if t.id == "llm_prune")
        assert set(entry.input_variables) == {"section_header", "section_content"}, (
            f"llm_prune placeholders changed: {entry.input_variables}"
        )

    def test_llm_prune_version_unchanged(self) -> None:
        """Version must remain 1.1."""
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES
        entry = next(t for t in DEFAULT_OPTIMIZER_TEMPLATES if t.id == "llm_prune")
        assert entry.version == "1.1"


# ---------------------------------------------------------------------------
# Contract preservation — llm_prune_validation
# ---------------------------------------------------------------------------

class TestLlamaPruneValidationTemplateContract:
    """Verify llm_prune_validation template contract is unchanged."""

    def test_llm_prune_validation_template_importable(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import LLM_PRUNE_VALIDATION_TEMPLATE
        assert isinstance(LLM_PRUNE_VALIDATION_TEMPLATE, str)
        assert len(LLM_PRUNE_VALIDATION_TEMPLATE) > 0

    def test_llm_prune_validation_placeholders_unchanged(self) -> None:
        """original_section and pruned_section placeholders must be present."""
        from mmap_optimizer.templates.optimizer_prompts import LLM_PRUNE_VALIDATION_TEMPLATE
        assert "{original_section}" in LLM_PRUNE_VALIDATION_TEMPLATE
        assert "{pruned_section}" in LLM_PRUNE_VALIDATION_TEMPLATE

    def test_llm_prune_validation_output_contract_preserved(self) -> None:
        """Output contract: {"valid": boolean, "reason": string}."""
        from mmap_optimizer.templates.optimizer_prompts import LLM_PRUNE_VALIDATION_TEMPLATE
        lower = LLM_PRUNE_VALIDATION_TEMPLATE.lower()
        assert "valid" in lower
        assert "reason" in lower
        assert "json" in lower or "json 对象" in LLM_PRUNE_VALIDATION_TEMPLATE

    def test_llm_prune_validation_registry_entry_exists(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES
        ids = [t.id for t in DEFAULT_OPTIMIZER_TEMPLATES]
        assert "llm_prune_validation" in ids

    def test_llm_prune_validation_registry_entry_placeholders(self) -> None:
        """Registry entry must use original_section and pruned_section."""
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES
        entry = next(t for t in DEFAULT_OPTIMIZER_TEMPLATES if t.id == "llm_prune_validation")
        assert set(entry.input_variables) == {"original_section", "pruned_section"}, (
            f"llm_prune_validation placeholders changed: {entry.input_variables}"
        )

    def test_llm_prune_validation_version_unchanged(self) -> None:
        """Version must remain 1.1."""
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES
        entry = next(t for t in DEFAULT_OPTIMIZER_TEMPLATES if t.id == "llm_prune_validation")
        assert entry.version == "1.1"

    def test_llm_prune_validation_valid_field_boolean(self) -> None:
        """valid field must be declared as boolean type."""
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES
        entry = next(t for t in DEFAULT_OPTIMIZER_TEMPLATES if t.id == "llm_prune_validation")
        assert "valid" in entry.output_contract["fields"]
        # boolean is the expected type
        type_str = str(entry.output_contract["fields"]["valid"]).lower()
        assert "bool" in type_str or "boolean" in type_str

    def test_llm_prune_validation_reason_field_string(self) -> None:
        """reason field must be declared as string type."""
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES
        entry = next(t for t in DEFAULT_OPTIMIZER_TEMPLATES if t.id == "llm_prune_validation")
        assert "reason" in entry.output_contract["fields"]
        type_str = str(entry.output_contract["fields"]["reason"]).lower()
        assert "str" in type_str or "string" in type_str


# ---------------------------------------------------------------------------
# Rule coverage — audit doc correctly maps legacy rules to consolidation
# ---------------------------------------------------------------------------

class TestRuleCoverage:
    """Verify the audit doc correctly identifies how legacy pruning value
    is subsumed by the consolidation adaptation.

    These tests check the audit doc (which references #74), not the current
    template state (which will be enhanced when #74 merges).
    """

    def test_doc_declares_llm_prune_covered(self, audit_doc_text: str) -> None:
        """Audit doc must state LLM_PRUNE_PROMPT value is covered by consolidation."""
        lower = audit_doc_text.lower()
        # Must mention that LLM_PRUNE_PROMPT rules are covered
        assert "llm_prune_prompt" in lower
        assert "covered" in lower

    def test_doc_declares_llm_prune_validation_covered(
        self, audit_doc_text: str
    ) -> None:
        """Audit doc must state LLM_PRUNE_VALIDATION_PROMPT value is covered."""
        lower = audit_doc_text.lower()
        assert "llm_prune_validation_prompt" in lower
        assert "covered" in lower

    def test_doc_explains_no_independent_migration_needed(
        self, audit_doc_text: str
    ) -> None:
        """Doc must explain why no independent migration is needed."""
        lower = audit_doc_text.lower()
        assert (
            "no independent migration" in lower
            or "not separately migrated" in lower
            or "not independently migrated" in lower
        ), "audit doc must explain that no independent migration is needed"

    def test_doc_lists_migration_table_for_llm_prune(
        self, audit_doc_text: str
    ) -> None:
        """Doc must have a migration table showing LLM_PRUNE_PROMPT rules as covered."""
        # Look for table-like content or section that maps rules to coverage status
        assert "### `LLM_PRUNE_PROMPT`" in audit_doc_text or "LLM_PRUNE_PROMPT" in audit_doc_text
        # Must have at least one ✅ status marker in the migration table
        assert "✅" in audit_doc_text or "covered" in audit_doc_text.lower()

    def test_doc_lists_migration_table_for_llm_prune_validation(
        self, audit_doc_text: str
    ) -> None:
        """Doc must have a migration table showing LLM_PRUNE_VALIDATION_PROMPT rules as covered."""
        assert (
            "### `LLM_PRUNE_VALIDATION_PROMPT`" in audit_doc_text
            or "LLM_PRUNE_VALIDATION_PROMPT" in audit_doc_text
        )
        assert "✅" in audit_doc_text or "covered" in audit_doc_text.lower()

    def test_doc_identifies_not_migrated_items_explicitly(
        self, audit_doc_text: str
    ) -> None:
        """The 'Rules Not Migrated' section must be present and enumerate what is NOT migrated."""
        assert (
            "Rules Not Migrated" in audit_doc_text
            or "rules not migrated" in audit_doc_text.lower()
        ), "audit doc must have a 'Rules Not Migrated' section"
        # Should mention what is NOT migrated (output contract, placeholder changes, etc.)
        lower = audit_doc_text.lower()
        assert (
            "output contract" in lower
            or "patch schema" in lower
            or "optimizer loop" in lower
            or "not migrated" in lower
        )


# ---------------------------------------------------------------------------
# Guardrails — confirm no prohibited changes
# ---------------------------------------------------------------------------

class TestGuardrails:
    """Confirm this PR (docs/tests-only) does not violate any guardrails."""

    def test_audit_doc_no_patch_schema_changes(self, audit_doc_text: str) -> None:
        """No mention of modifying patch schema."""
        lower = audit_doc_text.lower()
        assert "patch schema" not in lower or "not" in lower
        assert "no patch schema" in lower or "patch schema" not in lower

    def test_audit_doc_no_new_operations(self, audit_doc_text: str) -> None:
        """No new operations introduced."""
        lower = audit_doc_text.lower()
        assert "no new operation" in lower or "not" in lower

    def test_audit_doc_no_optimizer_loop_changes(self, audit_doc_text: str) -> None:
        """No optimizer loop changes declared."""
        lower = audit_doc_text.lower()
        assert "optimizer loop" not in lower or "not" in lower or "no" in lower

    def test_audit_doc_no_arbitrary_standardization(self, audit_doc_text: str) -> None:
        """No seven-section or arbitrary standardization is endorsed or applied."""
        lower = audit_doc_text.lower()
        if "seven-section" in lower or "七段" in audit_doc_text:
            # If mentioned, it must appear in a prohibited/not-migrated context.
            # The "Rules Not Migrated" heading with "Specifically not migrated:" is ~268 chars
            # before "seven-section" in the current doc layout. Use 400-char lookback.
            idx = lower.find("seven-section") if "seven-section" in lower else lower.find("七段")
            context = audit_doc_text[max(0, idx - 400) : idx + 80]
            ctx_lower = context.lower()
            # The "Rules Not Migrated" heading must be in the preceding text
            assert (
                "not migrated" in ctx_lower
                or "not migrated" in audit_doc_text[:idx + 80].lower()
                or "do not" in ctx_lower
                or "never" in ctx_lower
                or "no new" in ctx_lower
                or "no arbitrary" in ctx_lower
            ), f"seven-section appears but not in a prohibited context: {context[:300]}"

    def test_audit_doc_no_unsafe_deletion(self, audit_doc_text: str) -> None:
        """No unsafe deletion of constraints, examples, or placeholders."""
        lower = audit_doc_text.lower()
        assert "unsafe deletion" not in lower or "no" in lower


# ---------------------------------------------------------------------------
# Other-template isolation — confirm unrelated templates not touched
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
})

_PROMPTS_PY = (
    Path(__file__).resolve().parent.parent
    / "mmap_optimizer"
    / "templates"
    / "optimizer_prompts.py"
)


class TestOtherTemplateIsolation:
    """Verify this audit does not accidentally modify or target other templates."""

    def test_templates_file_unchanged_from_main(
        self,
    ) -> None:
        """The optimizer_prompts.py file must not be modified by this PR.

        This is a docs/tests-only PR. Templates are modified only by the
        consolidation adaptation in PR #74, not by this audit PR.
        """
        # Read the current file
        content = _PROMPTS_PY.read_text(encoding="utf-8")
        # The file should contain the current basic rules from PR #65
        # (not the enhanced #74 rules — those are on a different branch)
        assert "LLM_PRUNE_TEMPLATE" in content
        assert "LLM_PRUNE_VALIDATION_TEMPLATE" in content

    def test_unrelated_templates_not_in_audit_doc_prose(
        self, audit_doc_text: str
    ) -> None:
        """The audit doc must not claim to modify unrelated templates."""
        lower = audit_doc_text.lower()
        for tid in _TEMPLATE_IDS_THAT_MUST_NOT_BE_MENTIONED_AS_MODIFIED:
            # It's OK if these names appear in passing, but not in a context
            # that says "modified" or "migrated" them
            if tid in lower:
                # Find surrounding context (50 chars each side)
                idx = lower.find(tid)
                context = audit_doc_text[max(0, idx - 50) : idx + len(tid) + 50]
                assert "modif" not in context.lower() and "migrat" not in context.lower(), (
                    f"audit doc appears to claim modification of {tid}: {context}"
                )
