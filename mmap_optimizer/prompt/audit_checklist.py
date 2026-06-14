"""Explicit utility: audit-checklist report builder and validator.

This module provides deterministic data structures and helpers for building,
validating, and serializing structured audit-checklist reports. These reports
are intended for use as machine-readable + human-readable audit artifacts for
prompt rewrite, compression, repair, patch generation, and evaluation stages.

The caller invokes this explicitly. Nothing in ``mmap_optimizer`` calls it
by default, no optimizer-loop hook exists, and no LLM call is made.

Typical usage::

    from mmap_optimizer.prompt.audit_checklist import (
        AuditChecklistItem,
        build_audit_checklist_report,
        validate_audit_checklist_report,
        render_audit_checklist_summary,
    )

    items = [
        AuditChecklistItem(
            id="placeholder-preservation",
            dimension="placeholder_preservation",
            status="pass",
            evidence="All placeholders from original appear in rewritten.",
        ),
        AuditChecklistItem(
            id="no-hallucination",
            dimension="completeness",
            status="fail",
            evidence="Rewritten removed the 'DO NOT' clause.",
            issue="Critical safety constraint was dropped.",
            severity="blocker",
            suggested_fix="Re-add the 'DO NOT' clause verbatim.",
        ),
    ]

    report = build_audit_checklist_report(
        target_id="prompt-v3",
        items=items,
        metadata={"author": "audit-bot", "round": 2},
    )

    # Machine-readable validation.
    issues = validate_audit_checklist_report(report)
    if issues:
        print("Report has structural issues:", issues)

    # Human-readable summary.
    print(render_audit_checklist_summary(report))
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_STATUSES: frozenset[str] = frozenset({"pass", "warning", "fail"})
_VALID_SEVERITIES: frozenset[str] = frozenset(
    {"blocker", "major", "minor", "info"}
)

# Common audit dimensions — documented in the API contract but not enforced.
_COMMON_DIMENSIONS: frozenset[str] = frozenset(
    {
        "completeness",
        "constraint_preservation",
        "ambiguity_reduction",
        "output_schema",
        "placeholder_preservation",
        "payload_integrity",
        "format_validity",
        "semantic_risk",
        "safety_compliance",
    }
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditChecklistItem:
    """A single audit dimension result.

    Fields are deliberately narrow so callers can rely on stable names.
    ``severity`` defaults to ``"info"`` so callers that omit it are
    always structurally valid.
    """

    id: str
    dimension: str
    status: str
    evidence: str
    issue: str | None = None
    severity: str = "info"
    suggested_fix: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dimension": self.dimension,
            "status": self.status,
            "evidence": self.evidence,
            "issue": self.issue,
            "severity": self.severity,
            "suggested_fix": self.suggested_fix,
        }


@dataclass(frozen=True)
class AuditChecklistReport:
    """Full audit checklist report for a single target.

    ``failure_summary`` and ``repair_recommendation`` are populated
    automatically when there are failing or warning items; callers may also
    override them.
    """

    target_id: str
    overall_status: str
    items: tuple[AuditChecklistItem, ...]
    failure_summary: str | None = None
    repair_recommendation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "overall_status": self.overall_status,
            "items": [item.to_dict() for item in self.items],
            "failure_summary": self.failure_summary,
            "repair_recommendation": self.repair_recommendation,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Core report builder
# ---------------------------------------------------------------------------


def build_audit_checklist_report(
    *,
    target_id: str,
    items: Iterable[AuditChecklistItem | Mapping[str, Any]],
    metadata: Mapping[str, Any] | None = None,
) -> AuditChecklistReport:
    """Build a validated ``AuditChecklistReport``.

    Parameters
    ----------
    target_id:
        Identifier for the artifact being audited (e.g. prompt version ID,
        round number, or file name). Must be a non-empty string.
    items:
        Iterable of ``AuditChecklistItem`` dataclasses or dicts with the
        same field names. Dict values are copied before processing.
    metadata:
        Optional arbitrary key/value metadata to attach to the report
        (e.g. author, round, timestamp). Values should be JSON-safe.

    Returns
    -------
    AuditChecklistReport

    Raises
    ------
    TypeError
        If ``target_id`` is not a string, or if an item is neither an
        ``AuditChecklistItem`` nor a dict.

    The returned report has:
    - ``items`` as a ``tuple`` (deterministic order = insertion order).
    - ``overall_status`` auto-derived: fail > warning > pass.
    - ``failure_summary`` auto-generated if any item is fail.
    - ``repair_recommendation`` auto-generated if any item with a
      ``suggested_fix`` exists and overall_status is not pass.
    """
    if not isinstance(target_id, str):
        raise TypeError("target_id must be str, got %s" % type(target_id).__name__)

    # Normalise items, preserving insertion order.
    normalized: list[AuditChecklistItem] = []
    for raw in items:
        if isinstance(raw, AuditChecklistItem):
            # Normalize status/severity even for dataclass inputs to
            # ensure consistent casing.
            normalized.append(AuditChecklistItem(
                id=raw.id,
                dimension=raw.dimension,
                status=raw.status.lower(),
                evidence=raw.evidence,
                issue=raw.issue,
                severity=raw.severity.lower(),
                suggested_fix=raw.suggested_fix,
            ))
        elif isinstance(raw, Mapping):
            # Copy so we don't mutate the caller's dict.
            normalized.append(AuditChecklistItem(
                id=str(raw.get("id", "")),
                dimension=str(raw.get("dimension", "")),
                status=str(raw.get("status", "")).lower(),
                evidence=str(raw.get("evidence", "")),
                issue=raw.get("issue"),
                severity=str(raw.get("severity", "info")).lower(),
                suggested_fix=raw.get("suggested_fix"),
            ))
        else:
            raise TypeError(
                "items must be AuditChecklistItem or dict, got %s"
                % type(raw).__name__
            )

    # Derive overall_status.
    statuses = {item.status for item in normalized}
    if "fail" in statuses:
        overall_status = "fail"
    elif "warning" in statuses:
        overall_status = "warning"
    else:
        overall_status = "pass"

    # Generate failure_summary.
    failure_summary: str | None = None
    if overall_status != "pass":
        fail_items = [i for i in normalized if i.status == "fail"]
        summary_parts = []
        for item in fail_items:
            dim = item.dimension or "(unknown dimension)"
            sev = item.severity or "info"
            msg = item.issue or "(no issue description)"
            summary_parts.append("[%s][%s] %s" % (sev, dim, msg))
        failure_summary = " | ".join(summary_parts)

    # Generate repair_recommendation.
    repair_recommendation: str | None = None
    if overall_status != "pass":
        fixes = [
            i.suggested_fix
            for i in normalized
            if i.suggested_fix
        ]
        if fixes:
            repair_recommendation = " | ".join(
                "[%s] %s" % (i.id, i.suggested_fix) for i in normalized if i.suggested_fix
            )

    return AuditChecklistReport(
        target_id=target_id,
        overall_status=overall_status,
        items=tuple(normalized),
        failure_summary=failure_summary,
        repair_recommendation=repair_recommendation,
        metadata=dict(metadata) if metadata else {},
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_audit_checklist_report(
    report: AuditChecklistReport,
) -> tuple[str, ...]:
    """Validate a report's structural integrity.

    Returns a (possibly empty) tuple of issue strings. Empty tuple means
    the report is structurally valid.

    Validation rules
    ---------------
    - target_id must not be empty.
    - items must not be empty.
    - All item ids must be non-empty and unique.
    - All item dimensions must be non-empty.
    - status must be one of ``pass``, ``warning``, ``fail``.
    - severity must be one of ``blocker``, ``major``, ``minor``, ``info``.
    - status=pass requires a non-empty evidence.
    - status=warning requires a non-empty issue.
    - status=fail requires a non-empty issue.
    - overall_status must be consistent with the actual item statuses.
    - metadata values must be JSON-safe (checked via json.dumps attempt).
    """
    issues: list[str] = []

    if not report.target_id or not report.target_id.strip():
        issues.append("target_id is empty")

    if not report.items:
        issues.append("report has no items")
        return tuple(issues)

    # Check ids.
    ids_seen: dict[str, int] = {}
    for idx, item in enumerate(report.items):
        if not item.id or not item.id.strip():
            issues.append("item at index %d has empty id" % idx)
        else:
            ids_seen.setdefault(item.id, 0)
            ids_seen[item.id] += 1

    for id_val, count in ids_seen.items():
        if count > 1:
            issues.append("duplicate item id: %r (appears %d times)" % (id_val, count))

    # Check dimensions and statuses.
    for idx, item in enumerate(report.items):
        prefix = "item[%d] id=%r" % (idx, item.id)

        if not item.dimension or not item.dimension.strip():
            issues.append("%s: empty dimension" % prefix)

        if item.status not in _VALID_STATUSES:
            issues.append(
                "%s: invalid status %r (must be one of %s)"
                % (prefix, item.status, sorted(_VALID_STATUSES))
            )

        if item.severity not in _VALID_SEVERITIES:
            issues.append(
                "%s: invalid severity %r (must be one of %s)"
                % (prefix, item.severity, sorted(_VALID_SEVERITIES))
            )

        # Evidence guardrails.
        if item.status == "pass":
            if not item.evidence or not item.evidence.strip():
                issues.append(
                    "%s: status=pass requires non-empty evidence" % prefix
                )

        # Issue guardrails.
        if item.status in ("warning", "fail"):
            if not item.issue or not item.issue.strip():
                issues.append(
                    "%s: status=%s requires non-empty issue" % (prefix, item.status)
                )

    # overall_status consistency.
    statuses = {item.status for item in report.items}
    if "fail" in statuses:
        expected_overall = "fail"
    elif "warning" in statuses:
        expected_overall = "warning"
    else:
        expected_overall = "pass"

    if report.overall_status != expected_overall:
        issues.append(
            "overall_status is %r but should be %r based on items"
            % (report.overall_status, expected_overall)
        )

    # JSON-safety of metadata.
    try:
        json.dumps(report.metadata)
    except (TypeError, ValueError) as exc:
        issues.append("metadata is not JSON-safe: %s" % exc)

    return tuple(issues)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def audit_checklist_to_json(
    report: AuditChecklistReport,
    *,
    indent: int | None = 2,
    sort_keys: bool = False,
) -> str:
    """Serialize a report to a JSON string.

    ``indent`` controls pretty-printing (pass ``None`` for compact output).
    ``sort_keys`` makes output deterministic for non-semantic key ordering.
    """
    return json.dumps(report.to_dict(), indent=indent, sort_keys=sort_keys)


def audit_checklist_from_dict(data: Mapping[str, Any]) -> AuditChecklistReport:
    """Reconstruct a report from a plain dict.

    This is the inverse of ``AuditChecklistReport.to_dict()``.
    Raises ``TypeError`` or ``ValueError`` if the dict is malformed.
    """
    if not isinstance(data, Mapping):
        raise TypeError("data must be a dict-like, got %s" % type(data).__name__)

    d = dict(data)

    raw_items = d.get("items", [])
    if not isinstance(raw_items, (list, tuple)):
        raise ValueError("'items' must be a list")

    items: list[AuditChecklistItem] = []
    for raw_item in raw_items:
        if isinstance(raw_item, AuditChecklistItem):
            items.append(AuditChecklistItem(
                id=raw_item.id,
                dimension=raw_item.dimension,
                status=raw_item.status.lower(),
                evidence=raw_item.evidence,
                issue=raw_item.issue,
                severity=raw_item.severity.lower(),
                suggested_fix=raw_item.suggested_fix,
            ))
        elif isinstance(raw_item, Mapping):
            items.append(AuditChecklistItem(
                id=str(raw_item.get("id", "")),
                dimension=str(raw_item.get("dimension", "")),
                status=str(raw_item.get("status", "")).lower(),
                evidence=str(raw_item.get("evidence", "")),
                issue=raw_item.get("issue"),
                severity=str(raw_item.get("severity", "info")).lower(),
                suggested_fix=raw_item.get("suggested_fix"),
            ))
        else:
            raise ValueError(
                "each item must be dict or AuditChecklistItem, got %s"
                % type(raw_item).__name__
            )

    return AuditChecklistReport(
        target_id=str(d.get("target_id", "")),
        overall_status=str(d.get("overall_status", "")).lower(),
        items=tuple(items),
        failure_summary=d.get("failure_summary"),
        repair_recommendation=d.get("repair_recommendation"),
        metadata=dict(d.get("metadata", {})),
    )


# ---------------------------------------------------------------------------
# Human-readable rendering
# ---------------------------------------------------------------------------


def render_audit_checklist_summary(report: AuditChecklistReport) -> str:
    """Render a human-readable audit summary.

    Output is plain text (no markdown dependency) and is suitable for
    printing or logging. It does **not** include every item detail — use
    ``audit_checklist_to_json`` for machine-readable detail.
    """
    fail_count = sum(1 for i in report.items if i.status == "fail")
    warn_count = sum(1 for i in report.items if i.status == "warning")
    pass_count = sum(1 for i in report.items if i.status == "pass")
    blocker_count = sum(
        1 for i in report.items if i.severity == "blocker"
    )
    major_count = sum(1 for i in report.items if i.severity == "major")

    lines = [
        "=" * 60,
        "AUDIT REPORT: %s" % report.target_id,
        "=" * 60,
        "Overall status : %s" % report.overall_status.upper(),
        "Items          : fail=%d  warning=%d  pass=%d"
        % (fail_count, warn_count, pass_count),
        "Severity       : blocker=%d  major=%d"
        % (blocker_count, major_count),
    ]

    if report.failure_summary:
        lines.append("-" * 60)
        lines.append("FAILURE SUMMARY:")
        lines.append(report.failure_summary)

    if report.repair_recommendation:
        lines.append("-" * 60)
        lines.append("REPAIR RECOMMENDATION:")
        lines.append(report.repair_recommendation)

    lines.append("=" * 60)
    return "\n".join(lines)
