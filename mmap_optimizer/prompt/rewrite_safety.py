"""Explicit utility: prompt rewrite safety report wrapper.

This module combines four pre-existing deterministic utilities into a single
structured report for callers who want to audit a prompt rewrite before using
it:

1. JSON repair (optional)    (``mmap_optimizer.prompt.json_repair``)
2. numbering-only-refactor   (``mmap_optimizer.prompt.numbering_refactor``)
3. immutable-payload check   (``mmap_optimizer.prompt.immutable_payload``)
4. audit-checklist report    (``mmap_optimizer.prompt.audit_checklist``)

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
from mmap_optimizer.prompt.json_repair import (
    JsonRepairResult,
    repair_json_output,
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

    JSON repair fields:
    - ``json_repair_applied``: True iff ``apply_json_repair=True`` was passed.
    - ``json_repair_ok``: True/False if repair was applied; None otherwise.
    - ``json_repair_issue_count``: Number of issues from JSON repair; 0 if
      not applied.
    - ``json_repaired_text``: The repaired text if repair was applied and
      succeeded; None otherwise.
    - ``json_repaired_hash``: SHA-256 of ``json_repaired_text`` if present;
      None otherwise.
    """

    target_id: str
    ok: bool
    overall_status: str
    original_hash: str
    rewritten_hash: str
    json_repaired_hash: str | None
    normalized_rewritten_hash: str
    numbering_issue_count: int
    immutable_payload_issue_count: int
    audit_issue_count: int
    json_repair_applied: bool
    json_repair_ok: bool | None
    json_repair_issue_count: int
    json_repaired_text: str | None
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
            "json_repaired_hash": self.json_repaired_hash,
            "normalized_rewritten_hash": self.normalized_rewritten_hash,
            "numbering_issue_count": self.numbering_issue_count,
            "immutable_payload_issue_count": self.immutable_payload_issue_count,
            "audit_issue_count": self.audit_issue_count,
            "json_repair_applied": self.json_repair_applied,
            "json_repair_ok": self.json_repair_ok,
            "json_repair_issue_count": self.json_repair_issue_count,
            "json_repaired_text": self.json_repaired_text,
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
    apply_json_repair: bool = False,
    protected_placeholders: Iterable[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PromptRewriteSafetyReport:
    """Build a deterministic rewrite-safety audit report.

    Steps executed (in order, all in-memory, no filesystem writes):

    1. Hash ``original`` and ``rewritten`` via SHA-256.
    2. If *apply_json_repair* is True, run ``repair_json_output(rewritten)``.
       - If repair succeeds, use ``repaired_text`` for subsequent steps.
       - If repair fails, continue with original ``rewritten`` and mark
         ``ok=False``, ``overall_status="fail"``.
    3. Optionally normalize numbering in the (possibly repaired) text
       (``refactor_prompt_numbering_only``) if *apply_numbering_refactor* is
       True; otherwise *normalized_rewritten* == input text.
    4. Count numbering issues in the input text via ``detect_numbering_issues``.
    5. Run ``validate_immutable_payload(original, normalized_rewritten)``.
    6. Build ``AuditChecklistItem`` entries for ``payload_integrity``,
       ``format_validity``, ``rewrite_traceability``, and optionally
       ``json-repair`` (if JSON repair was applied).
    7. Emit a final ``PromptRewriteSafetyReport`` with aggregate counts and
       overall_status.

    The function is deterministic: the same inputs always yield the same
    outputs. It never writes to disk and never calls an LLM.

    ``apply_json_repair`` defaults to ``False`` to preserve backward
    compatibility. Only callers who explicitly set it to ``True`` will
    have JSON repair applied.
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

    # Step 1 — optional JSON repair
    json_repair_applied = apply_json_repair
    json_repair_ok: bool | None = None
    json_repair_issue_count = 0
    json_repaired_text: str | None = None
    json_repaired_hash: str | None = None
    json_repair_result: JsonRepairResult | None = None

    text_for_numbering = rewritten  # text that goes into numbering step

    if apply_json_repair:
        json_repair_result = repair_json_output(rewritten)
        json_repair_ok = json_repair_result.ok
        json_repair_issue_count = len(json_repair_result.issues)
        if json_repair_result.ok:
            json_repaired_text = json_repair_result.repaired_text
            json_repaired_hash = hashlib.sha256(
                json_repaired_text.encode("utf-8")
            ).hexdigest()
            text_for_numbering = json_repaired_text
        else:
            # Repair failed: continue with original rewritten text
            # normalized_rewritten will be based on original rewritten
            json_repaired_text = None
            json_repaired_hash = None

    # Step 2 — numbering normalization
    numbering_issues = list(detect_numbering_issues(text_for_numbering))
    if apply_numbering_refactor:
        normalized_rewritten = refactor_prompt_numbering_only(text_for_numbering)
    else:
        normalized_rewritten = text_for_numbering
    normalized_rewritten_hash = hashlib.sha256(
        normalized_rewritten.encode("utf-8")
    ).hexdigest()

    # Step 3 — immutable payload validation
    immutable_result = validate_immutable_payload(
        original,
        normalized_rewritten,
        protected_placeholders=protected_placeholders,
    )
    immutable_issues = list(immutable_result.issues)

    # Step 4 — audit items
    audit_items: list[AuditChecklistItem] = []

    # 4a. json-repair (if applied)
    if apply_json_repair and json_repair_result is not None:
        if json_repair_result.ok:
            # Check if repair actually changed the text
            repair_changed = json_repaired_text != rewritten
            status = "warning" if repair_changed else "pass"
            severity = "minor" if repair_changed else "info"
            evidence = (
                "JSON repair succeeded. "
                "issue_count=%d; repaired_text_length=%d; "
                "position_valid=True; repair_changed=%s"
                % (
                    json_repair_issue_count,
                    len(json_repaired_text) if json_repaired_text else 0,
                    repair_changed,
                )
            )
            issue = None
            suggested_fix = None
            if repair_changed:
                issue = "JSON was not position-valid; repairs applied."
                suggested_fix = (
                    "Ensure model outputs position-valid JSON "
                    "(no fences, no surrounding prose, no trailing commas)."
                )
            audit_items.append(
                AuditChecklistItem(
                    id="json-repair",
                    dimension="format_validity",
                    status=status,
                    evidence=evidence,
                    issue=issue,
                    severity=severity,
                    suggested_fix=suggested_fix,
                )
            )
        else:
            # JSON repair failed
            issue_summary = "; ".join(
                i.issue_type for i in json_repair_result.issues[:3]
            )
            audit_items.append(
                AuditChecklistItem(
                    id="json-repair",
                    dimension="format_validity",
                    status="fail",
                    evidence="JSON repair failed. "
                    "issue_count=%d; issue_types=%s"
                    % (json_repair_issue_count, issue_summary),
                    issue="Rewritten text is not valid JSON and could not be "
                    "automatically repaired. Issues: %s" % issue_summary,
                    severity="blocker",
                    suggested_fix=(
                        "Produce position-valid JSON before safety validation."
                    ),
                )
            )

    # 4b. payload_integrity
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

    # 4c. format_validity (numbering)
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

    # 4d. rewrite_traceability (hash chain)
    hash_chain_parts = []
    hash_chain_parts.append("rewritten_hash=%s" % rewritten_hash[:12])
    if json_repaired_hash is not None:
        hash_chain_parts.append("json_repaired_hash=%s" % json_repaired_hash[:12])
    hash_chain_parts.append("normalized_rewritten_hash=%s" % normalized_rewritten_hash[:12])
    hash_chain_evidence = "Hash chain: " + "; ".join(hash_chain_parts)

    # Determine if any transformation occurred
    text_changed = False
    change_description = []
    if json_repaired_hash is not None and json_repaired_hash != rewritten_hash:
        text_changed = True
        change_description.append("JSON repair modified text")
    if normalized_rewritten_hash != (
        json_repaired_hash if json_repaired_hash else rewritten_hash
    ):
        text_changed = True
        change_description.append("Numbering refactor modified text")

    if not text_changed and not apply_json_repair:
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
                status="warning" if text_changed else "pass",
                evidence=hash_chain_evidence,
                issue=(
                    "Text transformations applied: %s"
                    % ", ".join(change_description)
                ) if change_description else None,
                severity="minor" if text_changed else "info",
                suggested_fix=(
                    "Use report.normalized_rewritten (already computed in "
                    "this report) instead of the raw rewritten text if you "
                    "want to ship a cleaned version."
                ) if text_changed else None,
            )
        )

    # Step 5 — compose audit report
    audit_metadata = {
        "original_hash": original_hash,
        "rewritten_hash": rewritten_hash,
        "normalized_rewritten_hash": normalized_rewritten_hash,
        "apply_numbering_refactor": apply_numbering_refactor,
        "apply_json_repair": apply_json_repair,
    }
    if json_repaired_hash is not None:
        audit_metadata["json_repaired_hash"] = json_repaired_hash

    audit_report = build_audit_checklist_report(
        target_id=target_id,
        items=audit_items,
        metadata=audit_metadata,
    )

    # Aggregate issue counts for easy reference
    numbering_issue_count = len(numbering_issues)
    immutable_payload_issue_count = len(immutable_issues)
    audit_issue_count = sum(
        1 for item in audit_report.items if item.status != "pass"
    )

    # overall_status is delegated to audit_report; ok is True iff the
    # combined report is not "fail" AND the immutable-payload validation
    # succeeded AND (if JSON repair was applied) it succeeded.
    # This is a conservative gate.
    json_repair_failed = apply_json_repair and json_repair_ok is False
    ok = (
        immutable_result.ok
        and audit_report.overall_status != "fail"
        and not json_repair_failed
    )

    return PromptRewriteSafetyReport(
        target_id=target_id,
        ok=ok,
        overall_status=audit_report.overall_status,
        original_hash=original_hash,
        rewritten_hash=rewritten_hash,
        json_repaired_hash=json_repaired_hash,
        normalized_rewritten_hash=normalized_rewritten_hash,
        numbering_issue_count=numbering_issue_count,
        immutable_payload_issue_count=immutable_payload_issue_count,
        audit_issue_count=audit_issue_count,
        json_repair_applied=json_repair_applied,
        json_repair_ok=json_repair_ok,
        json_repair_issue_count=json_repair_issue_count,
        json_repaired_text=json_repaired_text,
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

    Handles both legacy dicts (without JSON repair fields) and new dicts
    (with JSON repair fields) for backward compatibility.
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
        json_repaired_hash=d.get("json_repaired_hash"),  # Optional, may be None
        normalized_rewritten_hash=str(d.get("normalized_rewritten_hash", "")),
        numbering_issue_count=int(d.get("numbering_issue_count", 0)),
        immutable_payload_issue_count=int(
            d.get("immutable_payload_issue_count", 0)
        ),
        audit_issue_count=int(d.get("audit_issue_count", 0)),
        json_repair_applied=bool(d.get("json_repair_applied", False)),
        json_repair_ok=d.get("json_repair_ok"),  # Optional, may be None
        json_repair_issue_count=int(d.get("json_repair_issue_count", 0)),
        json_repaired_text=d.get("json_repaired_text"),  # Optional, may be None
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
    ]

    if report.json_repair_applied:
        lines.append("json_repair    : applied=%s, ok=%s, issues=%d"
            % (report.json_repair_applied, report.json_repair_ok,
               report.json_repair_issue_count))
        if report.json_repaired_hash:
            lines.append("json_repaired  : %s…" % report.json_repaired_hash[:12])

    lines.append("normalized_hash: %s…" % report.normalized_rewritten_hash[:12])
    lines.append("issue counts   : numbering=%d, payload=%d, audit_non_pass=%d"
        % (
            report.numbering_issue_count,
            report.immutable_payload_issue_count,
            report.audit_issue_count,
        ))

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
