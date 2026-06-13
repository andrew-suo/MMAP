from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SchemaValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    missing_required_fields: list[str] = field(default_factory=list)
    extra_fields: list[str] = field(default_factory=list)
    invalid_enum_fields: list[str] = field(default_factory=list)
    type_errors: list[str] = field(default_factory=list)


_JSON_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


class SimpleJsonSchemaValidator:
    """Small JSON-schema subset validator for MVP object outputs."""

    def validate(self, value: Any, schema: dict[str, Any], *, extra_fields_allowed: bool = False) -> SchemaValidationResult:
        result = SchemaValidationResult(valid=True)
        expected_type = schema.get("type")
        if expected_type and not isinstance(value, _JSON_TYPE_MAP.get(expected_type, object)):
            result.type_errors.append(f"root expected {expected_type}")
            result.valid = False
            return result
        if expected_type != "object" or not isinstance(value, dict):
            return result
        required = schema.get("required", [])
        for field in required:
            if field not in value:
                result.missing_required_fields.append(field)
        properties = schema.get("properties", {})
        if not extra_fields_allowed:
            result.extra_fields.extend(sorted(set(value) - set(properties)))
        for field, field_schema in properties.items():
            if field not in value:
                continue
            field_type = field_schema.get("type")
            if field_type and not isinstance(value[field], _JSON_TYPE_MAP.get(field_type, object)):
                if not (field_type == "number" and isinstance(value[field], int)):
                    result.type_errors.append(f"{field} expected {field_type}")
            enum = field_schema.get("enum")
            if enum is not None and value[field] not in enum:
                result.invalid_enum_fields.append(field)
        result.errors = result.missing_required_fields + result.extra_fields + result.invalid_enum_fields + result.type_errors
        result.valid = not result.errors
        return result
