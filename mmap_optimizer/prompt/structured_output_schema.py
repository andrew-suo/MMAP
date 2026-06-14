"""Explicit utility: structured output schema checker.

This module provides a deterministic, report-only schema contract
checker for JSON-like values. It answers the question:

    *Does a parsed value conform to a declared structural contract?*

It is intentionally NOT a repair utility:

- :mod:`mmap_optimizer.prompt.json_repair` turns raw text into a
  parseable JSON body (if possible).
- This module validates the *parsed* value against a lightweight
  schema-like contract.

The utility does NOT call any LLM, does NOT write files, does NOT
modify any default prompt, and is NOT wired into the optimizer loop,
CLI, or scenario runner. Callers invoke it explicitly.

Typical usage::

    from mmap_optimizer.prompt.structured_output_schema import (
        validate_structured_output,
        validate_json_text_against_schema,
        structured_schema_result_to_json,
    )

    schema = {
        "type": "object",
        "required": ["invoice_id", "amount", "currency"],
        "properties": {
            "invoice_id": {"type": "string"},
            "amount": {"type": "number"},
            "currency": {"type": "string"},
        },
        "additionalProperties": False,
    }

    value = {"invoice_id": "INV-1", "amount": 19.99, "currency": "USD"}
    result = validate_structured_output(value, schema)
    assert result.ok is True
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping


_VALID_TYPES = frozenset(
    {"object", "array", "string", "number", "integer", "boolean", "null", "any"}
)


def infer_json_type(value: Any) -> str:
    """Return the JSON type label for *value*.

    Distinguishes ``bool`` from ``int``, ``int`` from ``float``,
    ``None`` from other falsy values, etc.
    """

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "any":
        return True
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(
            value, bool
        )
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def stable_json_hash(value: Any) -> str:
    """Return a deterministic SHA-256 hash over a canonical JSON rendering.

    Falls back to a stable failure marker when *value* is not
    JSON-serializable.
    """

    try:
        text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        text = "__not_json_serializable__"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StructuredSchemaIssue:
    """A single defect detected during schema validation."""

    issue_type: str
    path: str
    expected: str | None = None
    actual: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "issue_type": self.issue_type,
            "path": self.path,
        }
        if self.expected is not None:
            out["expected"] = self.expected
        if self.actual is not None:
            out["actual"] = self.actual
        if self.detail is not None:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True)
class StructuredSchemaValidationResult:
    """Complete output of a schema validation pass."""

    ok: bool
    issues: tuple[StructuredSchemaIssue, ...]
    checked_paths: tuple[str, ...]
    schema_hash: str
    value_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.to_dict() for issue in self.issues],
            "checked_paths": list(self.checked_paths),
            "schema_hash": self.schema_hash,
            "value_hash": self.value_hash,
        }


def _append_path(base: str, segment: str) -> str:
    if base == "$":
        return "$." + segment
    return base + "." + segment


def _append_index(base: str, index: int) -> str:
    return base + "[" + str(index) + "]"


def validate_schema_contract(schema: Mapping[str, Any]) -> tuple[str, ...]:
    """Return issue messages describing problems in *schema* itself.

    Empty tuple means the schema contract is well-formed enough to be
    used with :func:`validate_structured_output`.
    """

    issues: list[str] = []
    if not isinstance(schema, Mapping):
        return ("schema must be a mapping",)

    schema_type = schema.get("type")
    if schema_type is None:
        issues.append("schema missing 'type'")
    elif not isinstance(schema_type, str):
        issues.append("schema 'type' must be a string")
    elif schema_type not in _VALID_TYPES:
        issues.append("unknown schema type: " + repr(schema_type))

    if schema_type == "object":
        required = schema.get("required")
        if required is not None:
            if not isinstance(required, (list, tuple)) or not all(
                isinstance(item, str) for item in required
            ):
                issues.append("'required' must be a list/tuple of strings")
        properties = schema.get("properties")
        if properties is not None and not isinstance(properties, Mapping):
            issues.append("'properties' must be a mapping")
        if isinstance(properties, Mapping):
            for key, subschema in properties.items():
                if not isinstance(key, str):
                    issues.append("'properties' keys must be strings")
                    continue
                sub_issues = validate_schema_contract(subschema)
                for sub in sub_issues:
                    issues.append("properties." + key + ": " + sub)
        additional_properties = schema.get("additionalProperties")
        if additional_properties is not None and not isinstance(additional_properties, bool):
            issues.append("'additionalProperties' must be a bool if present")

    if schema_type == "array":
        items = schema.get("items")
        if items is not None and not isinstance(items, Mapping):
            issues.append("'items' must be a mapping")
        if isinstance(items, Mapping):
            for sub in validate_schema_contract(items):
                issues.append("items: " + sub)

    return tuple(issues)


def _walk(
    value: Any,
    schema: Mapping[str, Any],
    path: str,
    issues: list[StructuredSchemaIssue],
    checked_paths: list[str],
) -> None:
    checked_paths.append(path)

    expected_type = schema.get("type", "any")
    if not isinstance(expected_type, str) or expected_type not in _VALID_TYPES:
        issues.append(
            StructuredSchemaIssue(
                issue_type="invalid_schema",
                path=path,
                expected="valid type",
                actual=repr(expected_type),
                detail="unknown schema type",
            )
        )
        return

    if expected_type != "any" and not _type_matches(value, expected_type):
        issues.append(
            StructuredSchemaIssue(
                issue_type="type_mismatch",
                path=path,
                expected=expected_type,
                actual=infer_json_type(value),
                detail=None,
            )
        )
        return

    if expected_type == "object" or (expected_type == "any" and isinstance(value, dict)):
        if isinstance(value, dict):
            required = schema.get("required")
            if isinstance(required, (list, tuple)):
                for key in required:
                    if isinstance(key, str) and key not in value:
                        issues.append(
                            StructuredSchemaIssue(
                                issue_type="required_field_missing",
                                path=_append_path(path, key),
                                detail="required field missing",
                            )
                        )
            properties = schema.get("properties")
            if isinstance(properties, Mapping):
                for key, subschema in properties.items():
                    if isinstance(key, str) and key in value:
                        _walk(value[key], subschema, _append_path(path, key), issues, checked_paths)
            additional_properties = schema.get("additionalProperties")
            if additional_properties is False:
                known = set()
                if isinstance(properties, Mapping):
                    known = {k for k in properties if isinstance(k, str)}
                for key in value:
                    if isinstance(key, str) and key not in known:
                        issues.append(
                            StructuredSchemaIssue(
                                issue_type="unknown_field",
                                path=_append_path(path, key),
                                detail="additionalProperties=False disallows unknown fields",
                            )
                        )
        return

    if expected_type == "array" or (expected_type == "any" and isinstance(value, list)):
        if isinstance(value, list):
            items_schema = schema.get("items")
            if isinstance(items_schema, Mapping):
                for idx, item in enumerate(value):
                    _walk(item, items_schema, _append_index(path, idx), issues, checked_paths)
        return


def validate_structured_output(
    value: Any,
    schema: Mapping[str, Any],
) -> StructuredSchemaValidationResult:
    """Validate *value* against the lightweight schema contract *schema*.

    Returns a :class:`StructuredSchemaValidationResult` describing the
    outcome. Never raises — malformed schemas are reported via
    ``invalid_schema`` issues.
    """

    issues: list[StructuredSchemaIssue] = []
    checked_paths: list[str] = []

    schema_contract_issues = validate_schema_contract(schema)
    if schema_contract_issues:
        issues.append(
            StructuredSchemaIssue(
                issue_type="invalid_schema",
                path="$",
                detail="; ".join(schema_contract_issues),
            )
        )
        return StructuredSchemaValidationResult(
            ok=False,
            issues=tuple(issues),
            checked_paths=("$",),
            schema_hash=stable_json_hash(schema),
            value_hash=stable_json_hash(value),
        )

    _walk(value, schema, "$", issues, checked_paths)

    return StructuredSchemaValidationResult(
        ok=not bool(issues),
        issues=tuple(issues),
        checked_paths=tuple(sorted(set(checked_paths))),
        schema_hash=stable_json_hash(schema),
        value_hash=stable_json_hash(value),
    )


def validate_json_text_against_schema(
    text: str,
    schema: Mapping[str, Any],
) -> StructuredSchemaValidationResult:
    """Parse *text* with :func:`json.loads` and validate against *schema*.

    Returns ``ok=False`` with a ``json_parse_failed`` issue when the
    text cannot be parsed. This function does NOT call any JSON repair
    helper — if the caller wants repair, it should run
    :mod:`mmap_optimizer.prompt.json_repair` first and then call this
    function on the result.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a str")

    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        schema_contract_issues = validate_schema_contract(schema)
        issues: tuple[StructuredSchemaIssue, ...] = (
            StructuredSchemaIssue(
                issue_type="json_parse_failed",
                path="$",
                detail="json.loads failed to parse text",
            ),
        )
        if schema_contract_issues:
            issues = issues + (
                StructuredSchemaIssue(
                    issue_type="invalid_schema",
                    path="$",
                    detail="; ".join(schema_contract_issues),
                ),
            )
        return StructuredSchemaValidationResult(
            ok=False,
            issues=issues,
            checked_paths=("$",),
            schema_hash=stable_json_hash(schema),
            value_hash=stable_json_hash(text),
        )

    return validate_structured_output(value, schema)


def structured_schema_result_to_json(result: StructuredSchemaValidationResult) -> str:
    """Render *result* to a canonical JSON string."""

    return json.dumps(result.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "StructuredSchemaIssue",
    "StructuredSchemaValidationResult",
    "infer_json_type",
    "stable_json_hash",
    "validate_schema_contract",
    "validate_structured_output",
    "validate_json_text_against_schema",
    "structured_schema_result_to_json",
]
