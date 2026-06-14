"""Scenario-gated prompt utility runner.

This module provides an explicit-call orchestrator that runs one or more
prompt utilities against an original/rewritten text pair and returns a
structured report. It is the report-only entry point for callers (humans,
CI pipelines, or future scenario workflows) who want to audit prompt
rewrites without modifying anything.

**Default state: runner disabled.** No utility runs unless
``config.enabled=True`` is passed explicitly.

**Default behavior: report-only.** This module never modifies any file,
never applies a repair to a production prompt, and never calls an LLM.

Nothing in ``mmap_optimizer`` imports this module automatically.

Typical usage::

    from mmap_optimizer.prompt.utility_runner import (
        PromptUtilityRunConfig,
        PromptUtilityRunResult,
        run_prompt_utilities,
        render_prompt_utility_run_summary,
    )

    config = PromptUtilityRunConfig(
        enabled=True,
        utilities=("rewrite_safety",),
        apply_json_repair=True,
    )
    result = run_prompt_utilities(
        target_id="prompt-v3-to-v4",
        original=original_text,
        rewritten=candidate_rewrite,
        config=config,
    )
    if not result.ok:
        print(render_prompt_utility_run_summary(result))
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from mmap_optimizer.prompt.audit_checklist import (
    build_audit_checklist_report,
)
from mmap_optimizer.prompt.immutable_payload import (
    validate_immutable_payload,
)
from mmap_optimizer.prompt.json_repair import (
    repair_json_output,
)
from mmap_optimizer.prompt.numbering_refactor import (
    detect_numbering_issues,
    refactor_prompt_numbering_only,
)
from mmap_optimizer.prompt.rewrite_safety import (
    build_prompt_rewrite_safety_report,
)


# ---------------------------------------------------------------------------
# Supported utility names
# ---------------------------------------------------------------------------

SUPPORTED_UTILITIES: frozenset[str] = frozenset({
    "json_repair",
    "numbering_refactor",
    "immutable_payload",
    "audit_checklist",
    "rewrite_safety",
})


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromptUtilityRunConfig:
    """Configuration for a prompt utility run.

    ``enabled`` must be explicitly set to ``True`` to run any utility.
    ``report_only`` is ``True`` by default — nothing is modified or written.
    ``utilities`` is a tuple of utility names to execute.
    """

    enabled: bool = False
    utilities: tuple[str, ...] = ()
    apply_json_repair: bool = False
    apply_numbering_refactor: bool = True
    report_only: bool = True
    protected_placeholders: tuple[str, ...] = ()
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        # Ensure utilities is a tuple of strings
        if not isinstance(self.enabled, bool):
            raise TypeError(
                "enabled must be bool, got %s" % type(self.enabled).__name__
            )
        if not isinstance(self.utilities, (tuple, list)):
            raise TypeError(
                "utilities must be tuple or list, got %s"
                % type(self.utilities).__name__
            )


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromptUtilityRunResult:
    """Result of a prompt utility run.

    ``ok`` is ``True`` unless a validation error, unknown utility, or
    utility-reported failure occurred.

    ``reports`` is a dict mapping utility name to its report dict.
    ``issues`` is a tuple of human-readable issue strings.
    """

    target_id: str
    enabled: bool
    report_only: bool
    utilities: tuple[str, ...]
    ok: bool
    reports: dict[str, Any] = field(default_factory=dict)
    issues: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "enabled": self.enabled,
            "report_only": self.report_only,
            "utilities": list(self.utilities),
            "ok": self.ok,
            "reports": self.reports,
            "issues": list(self.issues),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_prompt_utility_run_config(
    config: PromptUtilityRunConfig,
) -> tuple[str, ...]:
    """Validate a run config and return a tuple of issue strings.

    Returns an empty tuple if the config is valid.
    Unknown utility names cause validation failure.
    """
    if not isinstance(config, PromptUtilityRunConfig):
        return ("config must be PromptUtilityRunConfig",)

    issues: list[str] = []
    seen: set[str] = set()
    for name in config.utilities:
        if name in seen:
            issues.append("duplicate utility name: %s" % name)
        seen.add(name)
        if name not in SUPPORTED_UTILITIES:
            issues.append("unknown utility: %s" % name)

    return tuple(issues)


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def run_prompt_utilities(
    *,
    target_id: str,
    original: str,
    rewritten: str,
    config: PromptUtilityRunConfig,
) -> PromptUtilityRunResult:
    """Run selected prompt utilities and return a structured report.

    Parameters
    ----------
    target_id: Identifier for this run (e.g. "prompt-v3-to-v4").
    original: The original prompt text.
    rewritten: The candidate rewritten prompt text.
    config: ``PromptUtilityRunConfig`` specifying which utilities to run.

    Returns
    -------
    ``PromptUtilityRunResult`` with ``reports`` keyed by utility name.

    Behavior
    --------
    - If ``config.enabled`` is ``False`` (the default), no utility runs.
      The result has ``enabled=False``, ``ok=True``, ``reports={}``.
    - If ``config.enabled`` is ``True`` but ``config.utilities`` is empty,
      the result has ``ok=True`` with a warning issue.
    - If ``config.enabled`` is ``True`` and an unknown utility is named,
      ``ok=False``.
    - Each utility's report is placed in ``reports[utility_name]``.
    - ``report_only=True`` (default) means nothing is modified or written.
    """
    if not isinstance(target_id, str):
        raise TypeError(
            "target_id must be str, got %s" % type(target_id).__name__
        )
    if not isinstance(original, str):
        raise TypeError(
            "original must be str, got %s" % type(original).__name__
        )
    if not isinstance(rewritten, str):
        raise TypeError(
            "rewritten must be str, got %s" % type(rewritten).__name__
        )
    if not isinstance(config, PromptUtilityRunConfig):
        raise TypeError(
            "config must be PromptUtilityRunConfig, got %s"
            % type(config).__name__
        )

    issues: list[str] = []
    reports: dict[str, Any] = {}
    ok = True

    # --- Disabled state ---
    if not config.enabled:
        if config.utilities:
            issues.append(
                "runner disabled; %d utility(s) specified but not executed"
                % len(config.utilities)
            )
        return PromptUtilityRunResult(
            target_id=target_id,
            enabled=False,
            report_only=config.report_only,
            utilities=config.utilities,
            ok=True,
            reports={},
            issues=tuple(issues),
            metadata=dict(config.metadata) if config.metadata else {},
        )

    # --- Enabled: validate utilities ---
    validation_issues = list(validate_prompt_utility_run_config(config))
    issues.extend(validation_issues)
    if validation_issues:
        ok = False
        return PromptUtilityRunResult(
            target_id=target_id,
            enabled=True,
            report_only=config.report_only,
            utilities=config.utilities,
            ok=False,
            reports={},
            issues=tuple(issues),
            metadata=dict(config.metadata) if config.metadata else {},
        )

    # --- Empty utilities list ---
    if not config.utilities:
        issues.append("no utilities specified; nothing to run")
        return PromptUtilityRunResult(
            target_id=target_id,
            enabled=True,
            report_only=config.report_only,
            utilities=(),
            ok=True,
            reports={},
            issues=tuple(issues),
            metadata=dict(config.metadata) if config.metadata else {},
        )

    # --- Run each utility ---
    protected = (
        tuple(config.protected_placeholders)
        if config.protected_placeholders
        else None
    )
    meta = dict(config.metadata) if config.metadata else {}

    for utility_name in config.utilities:
        try:
            if utility_name == "rewrite_safety":
                rs_report = build_prompt_rewrite_safety_report(
                    target_id=target_id,
                    original=original,
                    rewritten=rewritten,
                    apply_numbering_refactor=config.apply_numbering_refactor,
                    apply_json_repair=config.apply_json_repair,
                    protected_placeholders=protected,
                    metadata=meta,
                )
                reports["rewrite_safety"] = rs_report.to_dict()
                if not rs_report.ok:
                    ok = False
                    issues.append(
                        "rewrite_safety report: ok=False; "
                        "overall_status=%s" % rs_report.overall_status
                    )

            elif utility_name == "json_repair":
                jr_result = repair_json_output(rewritten)
                reports["json_repair"] = jr_result.to_dict()
                if not jr_result.ok:
                    ok = False
                    issues.append(
                        "json_repair: ok=False; %d issue(s)"
                        % len(jr_result.issues)
                    )

            elif utility_name == "numbering_refactor":
                detected = list(detect_numbering_issues(rewritten))
                normalized = refactor_prompt_numbering_only(rewritten)
                reports["numbering_refactor"] = {
                    "issue_count": len(detected),
                    "issues": [
                        {"line_number": i.line_number,
                         "original": i.original,
                         "expected": i.expected,
                         "issue_type": i.issue_type}
                        for i in detected
                    ],
                    "normalized_text": normalized,
                    # NOTE: normalized_text is for report only;
                    # nothing is applied to production prompts.
                }
                if detected:
                    issues.append(
                        "numbering_refactor: %d issue(s) detected"
                        % len(detected)
                    )

            elif utility_name == "immutable_payload":
                ip_result = validate_immutable_payload(
                    original,
                    rewritten,
                    protected_placeholders=protected,
                )
                reports["immutable_payload"] = ip_result.to_dict()
                if not ip_result.ok:
                    ok = False
                    issues.append(
                        "immutable_payload: ok=False; %d issue(s)"
                        % len(ip_result.issues)
                    )

            elif utility_name == "audit_checklist":
                # Minimal audit checklist: runner-level checks
                ac_items = []
                if config.enabled:
                    ac_items.append({
                        "id": "runner_enabled",
                        "dimension": "runner_state",
                        "status": "pass",
                        "evidence": "runner is enabled for this run",
                        "severity": "info",
                    })
                if config.report_only:
                    ac_items.append({
                        "id": "report_only",
                        "dimension": "runner_state",
                        "status": "pass",
                        "evidence": "runner is in report-only mode; no writes or applies",
                        "severity": "info",
                    })
                ac_items.append({
                    "id": "utility_list_known",
                    "dimension": "runner_state",
                    "status": "pass",
                    "evidence": "all %d utility(s) are known: %s"
                    % (len(config.utilities), ", ".join(config.utilities)),
                    "severity": "info",
                })
                ac_report = build_audit_checklist_report(
                    target_id=target_id,
                    items=ac_items,
                    metadata={
                        "runner_enabled": config.enabled,
                        "report_only": config.report_only,
                        "utilities": list(config.utilities),
                    },
                )
                reports["audit_checklist"] = ac_report.to_dict()
                if ac_report.overall_status == "fail":
                    ok = False
                    issues.append("audit_checklist: overall_status=fail")

        except Exception as exc:
            ok = False
            issues.append(
                "utility %s raised %s: %s"
                % (utility_name, type(exc).__name__, str(exc)[:120])
            )
            reports[utility_name] = {"_error": str(exc)}

    return PromptUtilityRunResult(
        target_id=target_id,
        enabled=True,
        report_only=config.report_only,
        utilities=config.utilities,
        ok=ok,
        reports=reports,
        issues=tuple(issues),
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def prompt_utility_run_result_to_json(
    result: PromptUtilityRunResult,
    *,
    indent: int | None = 2,
    sort_keys: bool = False,
) -> str:
    """Serialize a run result to a JSON string."""
    return json.dumps(result.to_dict(), indent=indent, sort_keys=sort_keys)


def prompt_utility_run_result_from_dict(
    data: Mapping[str, Any],
) -> PromptUtilityRunResult:
    """Reconstruct a run result from a plain dict."""
    if not isinstance(data, Mapping):
        raise TypeError(
            "data must be dict-like, got %s" % type(data).__name__
        )
    d = dict(data)
    return PromptUtilityRunResult(
        target_id=str(d.get("target_id", "")),
        enabled=bool(d.get("enabled", False)),
        report_only=bool(d.get("report_only", True)),
        utilities=tuple(str(u) for u in d.get("utilities", [])),
        ok=bool(d.get("ok", False)),
        reports=dict(d.get("reports", {})),
        issues=tuple(str(i) for i in d.get("issues", [])),
        metadata=dict(d.get("metadata", {})),
    )


# ---------------------------------------------------------------------------
# Human-readable summary
# ---------------------------------------------------------------------------

def render_prompt_utility_run_summary(
    result: PromptUtilityRunResult,
) -> str:
    """Render a compact, human-readable summary of a run result."""
    lines = [
        "=" * 60,
        "PROMPT UTILITY RUN RESULT: %s" % result.target_id,
        "=" * 60,
        "enabled     : %s" % result.enabled,
        "report_only : %s" % result.report_only,
        "ok          : %s" % result.ok,
        "utilities   : %s" % (", ".join(result.utilities) or "(none)"),
    ]

    if result.reports:
        lines.append("-" * 60)
        lines.append("reports:")
        for name, rep in result.reports.items():
            lines.append("  %s: (dict with %d key(s))"
                % (name, len(rep) if isinstance(rep, dict) else 0))

    if result.issues:
        lines.append("-" * 60)
        lines.append("issues:")
        for issue in result.issues:
            lines.append("  - %s" % issue)

    lines.append("=" * 60)
    return "\n".join(lines)
