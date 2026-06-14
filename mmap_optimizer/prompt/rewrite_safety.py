"""Explicit utility: prompt rewrite safety report wrapper.

This module combines three pre-existing deterministic utilities into a single
structured report for callers who want to audit a prompt rewrite before using
it:

1. numbering-only-refactor   (``mmap_optimizer.prompt.numbering_refactor``)
2. immutable-payload check   (``mmap_optimizer.prompt.immutable_payload``)
3. audit-checklist report    (``mmap_optimizer.prompt.audit_checklist``)

The caller invokes this explicitly. Nothing in the MMAP codebase calls this
automatically; no optimizer-loop hook exists; and no LLM call is made.

Typical usage::

    from mmap_optimizer.prompt.rewrite_safety import (
        build_prompt_rewrite_safety_report,
        render_prompt_rewrite_safety_summary,
    )

    report = build_prompt_rewrite_safety_report(
        target_id="prompt-v3-to-v4",
        original=original_text,
        rewritten=candidate_rewrite,
        apply_numbering_refactor=True,
        protected_placeholders=None,
        metadata={"author": "compression-v2", "round": 7},
    )

    # Decide for yourself what to do with ``report.ok`` and
    # ``report.overall_status``; nothing is applied automatically.
    if not report.ok:
        print(render_prompt_rewrite_safety_summary(report))

    # For CI / audit logging, serialize to JSON.
    from mmap_optimizer.prompt.rewrite_safety import (
        prompt_rewrite_safety_report_to_json,
    )
    with open("/tmp/safety-report.json", "w") as f:
        f.write(prompt_rewrite_safety_report_to_json(report))
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from mmap_optimizer.prompt.audit_checklist import (
    AuditChecklistItem,
    AuditChecklistReport,
    build_audit_checklist_report,
    audit_checklist_from_dict,
)
from mmap_optimizer.prompt.immutable_payload import (
    validate_immutable_payload,
)
from mmap_optimizer.prompt.numbering_refactor import (
    detect_numbering_issues,
    refactor_prompt_numbering_only,
)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromptRewriteSafetyReport:
    """Deterministic summary of a prompt rewrite audit.

    ``ok`` is ``True`` when the combined audit report is not ``fail``. It is
    a conservative gate: a purely numbering-related rewrite that otherwise
    preserves payload will be marked ``ok`` with overall_status="warning".

    ``normalized_rewritten`` contains the rewritten text after the optional
    numbering-refactor pass. It is intended for callers who want to see what
    a "structurally-clean" version of the rewrite looks like before manually
    applying it.
    """

    target_id: str
    ok: bool
    overall_status: str
    original_hash: str
    rewritten_hash: str
    normalized_rewritten_hash: str
    numbering_issue_count: int
    immutable_payload_issue_count: int
    audit_issue_count: int
    normalized_rewritten: str
    audit_report: AuditChecklistReport
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "ok": self.ok,
            "overall_status": self.overall_status,
            "original_hash": self.original_hash,
            "rewritten_hash": self.rewritten_hash,
            "normalized_rewritten_hash": self.normalized_rewritten_hash,
            "numbering_issue_count": self.numbering_issue_count,
            "immutable_payload_issue_count": self.immutable_payload_issue_count,
            "audit_issue_count": self.audit_issue_count,
            "normalized_rewritten": self.normalized_rewritten,
            "audit_report": self.audit_report.to_dict(),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------

def build_prompt_rewrite_safety_report(
    *,
    target_id: str,
    original: str,
    rewritten: str,
    apply_numbering_refactor: bool = True,
    protected_placeholders: Iterable[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PromptRewriteSafetyReport:
    """Build a deterministic rewrite-safety audit report.

    Steps executed (in order, all in-memory, no filesystem writes):

    1. Hash ``original`` and ``rewritten`` via SHA-256.
    2. Optionally normalize numbering in ``rewritten``
       (``refactor_prompt_numbering_only``) if *apply_numbering_refactor* is
       True; otherwise *normalized_rewritten* == *rewritten*.
    3. Count numbering issues in *rewritten* via ``detect_numbering_issues``.
    4. Run ``validate_immutable_payload(original, normalized_rewritten)``.
    5. Build three ``AuditChecklistItem`` entries for
       ``payload_integrity``, ``format_validity``, and ``rewrite_traceability``
       and construct an ``AuditChecklistReport``.
    6. Emit a final ``PromptRewriteSafetyReport`` with aggregate counts and
       overall_status.

    The function is deterministic: the same inputs always yield the same
    outputs. It never writes to disk and never calls an LLM.
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

    original_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
    rewritten_hash = hashlib.sha256(rewritten.encode("utf-8")).hexdigest()

    # Step 1 — numbering normalization
    numbering_issues = list(detect_numbering_issues(rewritten))
    if apply_numbering_refactor:
        normalized_rewritten = refactor_prompt_numbering_only(rewritten)
    else:
        normalized_rewritten = rewritten
    normalized_rewritten_hash = hashlib.sha256(
        normalized_rewritten.encode("utf-8")
    ).hexdigest()

    # Step 2 — immutable payload validation
    immutable_result = validate_immutable_payload(
        original,
        normalized_rewritten,
        protected_placeholders=protected_placeholders,
    )
    immutable_issues = list(immutable_result.issues)

    # Step 3 — audit items
    audit_items: list[AuditChecklistItem] = []

    # 3a. payload_integrity
    if immutable_result.ok:
        audit_items.append(
            AuditChecklistItem(
                id="payload_integrity",
                dimension="payload_integrity",
                status="pass",
                evidence="Immutable payload preserved. "
                "original_hash=%s; normalized_rewritten_hash=%s; "
                "placeholder count unchanged."
                % (original_hash[:12], normalized_rewritten_hash[:12]),
                severity="info",
            )
        )
    else:
        audit_items.append(
            AuditChecklistItem(
                id="payload_integrity",
                dimension="payload_integrity",
                status="fail",
                evidence="Immutable payload violated. "
                "Detected %d issue(s); first_issue=%s"
                % (
                    len(immutable_issues),
                    immutable_issues[0].issue_type
                    if immutable_issues
                    else "(unknown)",
                ),
                issue="The rewritten text modifies, adds, or removes content "
                "classified as immutable payload. "
                + "; ".join(i.detail[:240] for i in immutable_issues[:3]),
                severity="blocker",
                suggested_fix="Restore the original immutable payload "
                "(placeholders, field names, structural lines) before "
                "applying the rewrite; only cosmetic refactoring is safe.",
            )
        )

    # 3b. format_validity (numbering)
    if numbering_issues:
        if apply_numbering_refactor:
            audit_items.append(
                AuditChecklistItem(
                    id="format_validity",
                    dimension="format_validity",
                    status="warning",
                    evidence="Detected %d numbering issue(s) in rewritten "
                    "text; auto-normalized via refactor_prompt_numbering_only. "
                    "Sample types: %s"
                    % (
                        len(numbering_issues),
                        ", ".join(
                            sorted({i.issue_type for i in numbering_issues})
                        )[:80],
                    ),
                    issue="Markdown heading / list / step numbering is "
                    "inconsistent in the rewritten text.",
                    severity="minor",
                    suggested_fix=(
                        "Use mmap_optimizer.prompt.numbering_refactor."
                        "refactor_prompt_numbering_only to normalise numbering "
                        "before applying the rewrite."
                    ),
                )
            )
        else:
            audit_items.append(
                AuditChecklistItem(
                    id="format_validity",
                    dimension="format_validity",
                    status="warning",
                    evidence="Detected %d numbering issue(s); "
                    "apply_numbering_refactor=False so rewrite text was "
                    "left as-is. Sample types: %s"
                    % (
                        len(numbering_issues),
                        ", ".join(
                            sorted({i.issue_type for i in numbering_issues})
                        )[:80],
                    ),
                    issue="Numbering defects remain in rewritten text.",
                    severity="minor",
                    suggested_fix=(
                        "Call refactor_prompt_numbering_only(rewritten) to "
                        "clean up numbering; or re-run this utility with "
                        "apply_numbering_refactor=True."
                    ),
                )
            )
    else:
        audit_items.append(
            AuditChecklistItem(
                id="format_validity",
                dimension="format_validity",
                status="pass",
                evidence="No numbering issues detected in rewritten text.",
                severity="info",
            )
        )

    # 3c. rewrite_traceability (hash chain)
    if rewritten_hash == normalized_rewritten_hash:
        audit_items.append(
            AuditChecklistItem(
                id="rewrite_traceability",
                dimension="format_validity",
                status="pass",
                evidence="rewritten hash matches normalized hash: %s"
                % rewritten_hash[:16],
                severity="info",
            )
        )
    else:
        audit_items.append(
            AuditChecklistItem(
                id="rewrite_traceability",
                dimension="format_validity",
                status="warning",
                evidence="Numbering refactor produced different text; "
                "rewritten_hash=%s, normalized_rewritten_hash=%s"
                % (rewritten_hash[:12], normalized_rewritten_hash[:12]),
                issue="normalized_rewritten differs from rewritten due to "
                "numbering repair; apply the normalized version to ensure "
                "numbering consistency.",
                severity="minor",
                suggested_fix=(
                    "Use report.normalized_rewritten (already computed in "
                    "this report) instead of the raw rewritten text if you "
                    "want to ship a numbering-consistent version."
                ),
            )
        )

    # Step 4 — compose audit report
    audit_report = build_audit_checklist_report(
        target_id=target_id,
        items=audit_items,
        metadata={
            "original_hash": original_hash,
            "rewritten_hash": rewritten_hash,
            "normalized_rewritten_hash": normalized_rewritten_hash,
            "apply_numbering_refactor": apply_numbering_refactor,
        },
    )

    # Aggregate issue counts for easy reference
    numbering_issue_count = len(numbering_issues)
    immutable_payload_issue_count = len(immutable_issues)
    audit_issue_count = sum(
        1 for item in audit_report.items if item.status != "pass"
    )

    # overall_status is delegated to audit_report; ok is True iff the
    # combined report is not "fail" AND the immutable-payload validation
    # succeeded. This is a conservative gate: a pure numbering warning
    # will leave ok=True (callers can still inspect overall_status).
    ok = immutable_result.ok and audit_report.overall_status != "fail"

    return PromptRewriteSafetyReport(
        target_id=target_id,
        ok=ok,
        overall_status=audit_report.overall_status,
        original_hash=original_hash,
        rewritten_hash=rewritten_hash,
        normalized_rewritten_hash=normalized_rewritten_hash,
        numbering_issue_count=numbering_issue_count,
        immutable_payload_issue_count=immutable_payload_issue_count,
        audit_issue_count=audit_issue_count,
        normalized_rewritten=normalized_rewritten,
        audit_report=audit_report,
        metadata=dict(metadata) if metadata else {},
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def prompt_rewrite_safety_report_to_json(
    report: PromptRewriteSafetyReport,
    *,
    indent: int | None = 2,
    sort_keys: bool = False,
) -> str:
    """Serialize a report to a JSON string."""
    return json.dumps(report.to_dict(), indent=indent, sort_keys=sort_keys)


def prompt_rewrite_safety_report_from_dict(
    data: Mapping[str, Any],
) -> PromptRewriteSafetyReport:
    """Reconstruct a report from a plain dict.

    This is the inverse of ``PromptRewriteSafetyReport.to_dict()``. Raises
    ``TypeError`` if *data* is not a mapping.
    """
    if not isinstance(data, Mapping):
        raise TypeError(
            "data must be a dict-like, got %s" % type(data).__name__
        )

    d = dict(data)
    audit_report_data = d.get("audit_report") or {}
    audit_report = audit_checklist_from_dict(audit_report_data)

    return PromptRewriteSafetyReport(
        target_id=str(d.get("target_id", "")),
        ok=bool(d.get("ok", False)),
        overall_status=str(d.get("overall_status", "")),
        original_hash=str(d.get("original_hash", "")),
        rewritten_hash=str(d.get("rewritten_hash", "")),
        normalized_rewritten_hash=str(d.get("normalized_rewritten_hash", "")),
        numbering_issue_count=int(d.get("numbering_issue_count", 0)),
        immutable_payload_issue_count=int(
            d.get("immutable_payload_issue_count", 0)
        ),
        audit_issue_count=int(d.get("audit_issue_count", 0)),
        normalized_rewritten=str(d.get("normalized_rewritten", "")),
        audit_report=audit_report,
        metadata=dict(d.get("metadata", {})),
    )


# ---------------------------------------------------------------------------
# Human-readable summary
# ---------------------------------------------------------------------------

def render_prompt_rewrite_safety_summary(
    report: PromptRewriteSafetyReport,
) -> str:
    """Render a compact, human-readable summary of the safety report."""
    lines = [
        "=" * 60,
        "PROMPT REWRITE SAFETY REPORT: %s" % report.target_id,
        "=" * 60,
        "ok             : %s" % report.ok,
        "overall_status : %s" % report.overall_status,
        "original_hash  : %s…" % report.original_hash[:12],
        "rewritten_hash : %s…" % report.rewritten_hash[:12],
        "normalized_hash: %s…" % report.normalized_rewritten_hash[:12],
        "issue counts   : numbering=%d, payload=%d, audit_non_pass=%d"
        % (
            report.numbering_issue_count,
            report.immutable_payload_issue_count,
            report.audit_issue_count,
        ),
    ]

    if report.audit_report.failure_summary:
        lines.append("-" * 60)
        lines.append("failure_summary:")
        lines.append(report.audit_report.failure_summary)

    if report.audit_report.repair_recommendation:
        lines.append("-" * 60)
        lines.append("repair_recommendation:")
        lines.append(report.audit_report.repair_recommendation)

    lines.append("=" * 60)
    return "\n".join(lines)
