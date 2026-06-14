"""Prompt utility report artifact schema.

This module defines a stable, JSON-serializable artifact contract for
``PromptUtilityRunResult`` instances produced by the prompt utility runner.
It provides builders, serializers, validators, and deterministic hashes.
Nothing in this module writes to disk, calls an LLM, or imports the
optimizer loop, CLI, or scenario pipeline.

**Explicit invocation only.** Nothing in ``mmap_optimizer`` imports this
module automatically.

Typical usage::

    from mmap_optimizer.prompt.utility_runner import run_prompt_utilities
    from mmap_optimizer.prompt.utility_report_artifact import (
        build_prompt_utility_report_artifact,
        prompt_utility_report_artifact_to_json,
        validate_prompt_utility_report_artifact,
    )

    result = run_prompt_utilities(
        target_id="invoice-v3",
        original=original_text,
        rewritten=rewritten_text,
        config=PromptUtilityRunConfig(enabled=True, utilities=("structured_schema",)),
    )
    artifact = build_prompt_utility_report_artifact(
        result=result,
        original=original_text,
        rewritten=rewritten_text,
    )
    json_str = prompt_utility_report_artifact_to_json(artifact)
    issues = validate_prompt_utility_report_artifact(artifact)
    assert issues == ()
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, MutableMapping

from mmap_optimizer.prompt.utility_runner import (
    PromptUtilityRunResult,
)


# ---------------------------------------------------------------------------
# Artifact identity constants
# ---------------------------------------------------------------------------

ARTIFACT_TYPE: str = "prompt_utility_report"
ARTIFACT_VERSION: str = "1.0"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _canonical_json(value: Any) -> str:
    """Return a stable canonical JSON string for a value.

    Tuples are converted to lists so the output is always JSON-compatible.
    ``None`` is serialised as ``null``.
    """
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def stable_hash(value: Any) -> str:
    """Return a deterministic SHA-256 hex digest of the canonical JSON of *value*."""
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def canonicalize_for_report(value: Any) -> Any:
    """Recursively replace tuples with lists so the result is JSON-serializable.

    Mappings are returned as plain dicts; lists and tuples are converted to
    plain lists; primitives are returned unchanged.
    """
    if isinstance(value, Mapping):
        return {k: canonicalize_for_report(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonicalize_for_report(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Hashes dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromptUtilityReportHashes:
    """Content-addressable hashes for a report artifact.

    All hashes are SHA-256 digests of the canonical JSON (or raw string for
    ``original`` / ``rewritten``) so they are deterministic across Python
    invocations.
    """

    original_hash: str
    rewritten_hash: str
    reports_hash: str
    artifact_hash: str

    def to_dict(self) -> dict[str, str]:
        return {
            "original_hash": self.original_hash,
            "rewritten_hash": self.rewritten_hash,
            "reports_hash": self.reports_hash,
            "artifact_hash": self.artifact_hash,
        }


# ---------------------------------------------------------------------------
# Artifact dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromptUtilityReportArtifact:
    """Stable artifact wrapper for a ``PromptUtilityRunResult``.

    Fields mirror the runner result plus extra metadata that is useful for
    audit logs, CI artefacts, and downstream tooling.
    """

    artifact_type: str
    artifact_version: str
    target_id: str
    created_at: str
    ok: bool
    enabled: bool
    report_only: bool
    utilities: tuple[str, ...]
    issues: tuple[str, ...]
    reports: dict[str, Any]
    hashes: PromptUtilityReportHashes
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "artifact_version": self.artifact_version,
            "target_id": self.target_id,
            "created_at": self.created_at,
            "ok": self.ok,
            "enabled": self.enabled,
            "report_only": self.report_only,
            "utilities": list(self.utilities),
            "issues": list(self.issues),
            "reports": self.reports,
            "hashes": self.hashes.to_dict(),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_prompt_utility_report_artifact(
    *,
    result: PromptUtilityRunResult,
    original: str,
    rewritten: str,
    created_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PromptUtilityReportArtifact:
    """Build a ``PromptUtilityReportArtifact`` from a runner result and texts.

    Parameters
    ----------
    result:
        The ``PromptUtilityRunResult`` produced by the runner.
    original:
        The original (unmodified) prompt text.
    rewritten:
        The candidate rewritten prompt text.
    created_at:
        ISO-8601 UTC timestamp string. If omitted, a new one is generated.
    metadata:
        Extra key/value pairs to merge into ``artifact.metadata``.  Caller-
        supplied keys take precedence over values that already exist in
        ``result.metadata``.

    Returns
    -------
    ``PromptUtilityReportArtifact`` with deterministic hashes.

    The hash fields are computed as follows:

    - ``original_hash`` — SHA-256 of the raw original string.
    - ``rewritten_hash`` — SHA-256 of the raw rewritten string.
    - ``reports_hash`` — SHA-256 of the canonical JSON of ``result.reports``.
    - ``artifact_hash`` — SHA-256 of the canonical JSON of the artefact
      body **excluding** the ``artifact_hash`` key itself (self-referential
      exclusion).
    """
    if created_at is None:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Merge metadata: explicit wins
    merged_meta: dict[str, Any] = {**result.metadata}
    if metadata:
        merged_meta = {**merged_meta, **metadata}

    # Canonicalize reports for hashing and storage
    reports_canonical = canonicalize_for_report(result.reports)

    # Compute hashes
    original_hash = stable_hash(original)
    rewritten_hash = stable_hash(rewritten)
    reports_hash = stable_hash(reports_canonical)

    # Build the artifact body (without artifact_hash) to compute its digest
    artifact_body: dict[str, Any] = {
        "artifact_type": ARTIFACT_TYPE,
        "artifact_version": ARTIFACT_VERSION,
        "target_id": result.target_id,
        "created_at": created_at,
        "ok": result.ok,
        "enabled": result.enabled,
        "report_only": result.report_only,
        "utilities": list(result.utilities),
        "issues": list(result.issues),
        "reports": reports_canonical,
        "hashes": {
            "original_hash": original_hash,
            "rewritten_hash": rewritten_hash,
            "reports_hash": reports_hash,
            # artifact_hash excluded here — self-referential exclusion
        },
        "metadata": merged_meta,
    }
    artifact_hash = stable_hash(artifact_body)

    hashes = PromptUtilityReportHashes(
        original_hash=original_hash,
        rewritten_hash=rewritten_hash,
        reports_hash=reports_hash,
        artifact_hash=artifact_hash,
    )

    return PromptUtilityReportArtifact(
        artifact_type=ARTIFACT_TYPE,
        artifact_version=ARTIFACT_VERSION,
        target_id=result.target_id,
        created_at=created_at,
        ok=result.ok,
        enabled=result.enabled,
        report_only=result.report_only,
        utilities=result.utilities,
        issues=result.issues,
        reports=reports_canonical,
        hashes=hashes,
        metadata=merged_meta,
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def prompt_utility_report_artifact_to_json(
    artifact: PromptUtilityReportArtifact,
) -> str:
    """Serialise an artifact to a pretty-printed JSON string."""
    return json.dumps(
        artifact.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


def prompt_utility_report_artifact_from_dict(
    data: Mapping[str, Any],
) -> PromptUtilityReportArtifact:
    """Reconstruct an artifact from a plain dict.

    Parameters
    ----------
    data:
        A dict that was produced by ``artifact.to_dict()`` (or equivalent).

    Returns
    -------
    ``PromptUtilityReportArtifact``

    Raises
    ------
    ValueError
        If any required field is missing or has the wrong type.
    """
    if not isinstance(data, Mapping):
        raise ValueError(
            "data must be dict-like, got %s" % type(data).__name__
        )
    d = dict(data)

    def _req(key: str, expected_type: type | tuple[type, ...]) -> Any:
        val = d.get(key)
        if val is None:
            raise ValueError("missing required field: %s" % key)
        if not isinstance(val, expected_type):
            raise ValueError(
                "field %s must be %s, got %s" % (
                    key, expected_type.__name__, type(val).__name__
                )
            )
        return val

    artifact_type: str = _req("artifact_type", str)
    artifact_version: str = _req("artifact_version", str)
    target_id: str = _req("target_id", str)
    created_at: str = _req("created_at", str)
    ok: bool = _req("ok", bool)
    enabled: bool = _req("enabled", bool)
    report_only: bool = _req("report_only", bool)
    utilities_raw: list[Any] | tuple[Any, ...] = _req("utilities", (list, tuple))
    issues_raw: list[Any] | tuple[Any, ...] = _req("issues", (list, tuple))
    reports: dict[str, Any] = _req("reports", dict)
    hashes_map: dict[str, Any] = _req("hashes", dict)
    metadata: dict[str, Any] = _req("metadata", dict)

    # Validate sub-hashes
    for hk in ("original_hash", "rewritten_hash", "reports_hash", "artifact_hash"):
        hv = hashes_map.get(hk)
        if not isinstance(hv, str) or not hv:
            raise ValueError("hashes.%s must be a non-empty string" % hk)

    hashes = PromptUtilityReportHashes(
        original_hash=str(hashes_map["original_hash"]),
        rewritten_hash=str(hashes_map["rewritten_hash"]),
        reports_hash=str(hashes_map["reports_hash"]),
        artifact_hash=str(hashes_map["artifact_hash"]),
    )

    return PromptUtilityReportArtifact(
        artifact_type=artifact_type,
        artifact_version=artifact_version,
        target_id=target_id,
        created_at=created_at,
        ok=ok,
        enabled=enabled,
        report_only=report_only,
        utilities=tuple(str(u) for u in utilities_raw),
        issues=tuple(str(i) for i in issues_raw),
        reports=reports,
        hashes=hashes,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_prompt_utility_report_artifact(
    artifact: PromptUtilityReportArtifact | Mapping[str, Any],
) -> tuple[str, ...]:
    """Validate an artifact and return a tuple of human-readable issues.

    Returns an empty tuple if the artifact is well-formed.
    Does **not** raise on wrong input types — returns a single-item tuple
    describing the type problem.

    Validation covers: type/version constants, required non-empty fields,
    correct boolean/string/tuple/list types, required hash keys, hash
    re-computation integrity, and ``reports_hash`` integrity.
    """
    # Accept PromptUtilityReportArtifact via duck-typing (to_dict) or Mapping
    if hasattr(artifact, "to_dict"):
        d: dict[str, Any] = dict(artifact.to_dict())
    elif isinstance(artifact, Mapping):
        d = dict(artifact)
    else:
        return ("artifact must be dict-like, got %s" % type(artifact).__name__,)

    issues: list[str] = []

    # ── Type / version constants ────────────────────────────────────────
    if d.get("artifact_type") != ARTIFACT_TYPE:
        issues.append(
            "artifact_type must be %r, got %r" % (
                ARTIFACT_TYPE, d.get("artifact_type")
            )
        )

    if d.get("artifact_version") != ARTIFACT_VERSION:
        issues.append(
            "artifact_version must be %r, got %r" % (
                ARTIFACT_VERSION, d.get("artifact_version")
            )
        )

    # ── Non-empty string fields ──────────────────────────────────────────
    for field_name in ("target_id", "created_at"):
        val = d.get(field_name)
        if not isinstance(val, str) or not val:
            issues.append(
                "%s must be a non-empty string, got %r" % (field_name, val)
            )

    # ── Boolean fields ──────────────────────────────────────────────────
    for field_name in ("ok", "enabled", "report_only"):
        val = d.get(field_name)
        if not isinstance(val, bool):
            issues.append(
                "%s must be bool, got %s" % (field_name, type(val).__name__)
            )

    # ── Tuple/list fields ───────────────────────────────────────────────
    for field_name, allow_list in (("utilities", True), ("issues", True)):
        val = d.get(field_name)
        if not isinstance(val, (tuple, list)):
            issues.append(
                "%s must be tuple or list, got %s" % (
                    field_name, type(val).__name__
                )
            )
        elif not all(isinstance(item, str) for item in val):
            issues.append(
                "%s must contain only strings" % field_name
            )

    # ── reports must be a mapping ──────────────────────────────────────
    reports_val = d.get("reports")
    if not isinstance(reports_val, Mapping):
        issues.append(
            "reports must be dict-like, got %s" % type(reports_val).__name__
        )

    # ── metadata must be a mapping ──────────────────────────────────────
    metadata_val = d.get("metadata")
    if not isinstance(metadata_val, Mapping):
        issues.append(
            "metadata must be dict-like, got %s" % type(metadata_val).__name__
        )

    # ── hashes mapping ──────────────────────────────────────────────────
    hashes_val = d.get("hashes")
    if not isinstance(hashes_val, Mapping):
        issues.append(
            "hashes must be dict-like, got %s" % type(hashes_val).__name__
        )
    else:
        required_hash_keys = (
            "original_hash",
            "rewritten_hash",
            "reports_hash",
            "artifact_hash",
        )
        for hk in required_hash_keys:
            hv = hashes_val.get(hk)
            if not isinstance(hv, str) or not hv:
                issues.append(
                    "hashes.%s must be a non-empty string, got %r" % (
                        hk, hv
                    )
                )

    # ── Hash recomputation integrity ─────────────────────────────────────
    if isinstance(reports_val, Mapping) and isinstance(hashes_val, Mapping):
        reports_can = canonicalize_for_report(dict(reports_val))
        computed_reports_hash = stable_hash(reports_can)
        stored_reports_hash = hashes_val.get("reports_hash", "")
        if isinstance(stored_reports_hash, str) and stored_reports_hash:
            if computed_reports_hash != stored_reports_hash:
                issues.append(
                    "reports_hash mismatch: stored %r != computed %r"
                    % (stored_reports_hash, computed_reports_hash)
                )

        # Recompute artifact_hash (excluding artifact_hash itself)
        body_for_hash: dict[str, Any] = {
            k: v for k, v in d.items() if k != "hashes"
        }
        body_for_hash["hashes"] = {
            k: v
            for k, v in dict(hashes_val).items()
            if k != "artifact_hash"
        }
        # Normalize tuples/lists for consistency
        body_for_hash = canonicalize_for_report(body_for_hash)
        computed_artifact_hash = stable_hash(body_for_hash)
        stored_artifact_hash = hashes_val.get("artifact_hash", "")
        if isinstance(stored_artifact_hash, str) and stored_artifact_hash:
            if computed_artifact_hash != stored_artifact_hash:
                issues.append(
                    "artifact_hash mismatch: stored %r != computed %r"
                    % (stored_artifact_hash, computed_artifact_hash)
                )

    return tuple(issues)
