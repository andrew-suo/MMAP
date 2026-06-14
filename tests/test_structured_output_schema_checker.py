"""Contract tests for mmap_optimizer.prompt.structured_output_schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmap_optimizer.prompt.structured_output_schema import (
    StructuredSchemaIssue,
    StructuredSchemaValidationResult,
    infer_json_type,
    stable_json_hash,
    structured_schema_result_to_json,
    validate_json_text_against_schema,
    validate_schema_contract,
    validate_structured_output,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "mmap_optimizer" / "prompt" / "structured_output_schema.py"
MODULE_TEXT = MODULE_PATH.read_text(encoding="utf-8")


def _simple_invoice_schema():
    return {
        "type": "object",
        "required": ["invoice_id", "amount", "currency"],
        "properties": {
            "invoice_id": {"type": "string"},
            "amount": {"type": "number"},
            "currency": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "price"],
                    "properties": {
                        "name": {"type": "string"},
                        "price": {"type": "number"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    }


# ── Success cases ───────────────────────────────────────────────────────


def test_object_with_required_fields_passes():
    schema = _simple_invoice_schema()
    value = {"invoice_id": "INV-1", "amount": 19.99, "currency": "USD"}
    result = validate_structured_output(value, schema)
    assert result.ok is True
    assert result.issues == ()


def test_additional_properties_true_allows_unknown_fields():
    schema = {
        "type": "object",
        "required": ["a"],
        "properties": {"a": {"type": "string"}},
        "additionalProperties": True,
    }
    result = validate_structured_output({"a": "x", "b": 1, "c": True}, schema)
    assert result.ok is True


def test_additional_properties_omitted_allows_unknown_fields():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
    }
    result = validate_structured_output({"a": "x", "z": 123}, schema)
    assert result.ok is True


def test_nested_object_passes():
    schema = {
        "type": "object",
        "properties": {
            "inner": {
                "type": "object",
                "required": ["k"],
                "properties": {"k": {"type": "string"}},
                "additionalProperties": False,
            }
        },
        "additionalProperties": False,
    }
    result = validate_structured_output({"inner": {"k": "v"}}, schema)
    assert result.ok is True


def test_array_of_strings_passes():
    schema = {"type": "array", "items": {"type": "string"}}
    result = validate_structured_output(["a", "b", "c"], schema)
    assert result.ok is True


def test_array_of_objects_passes():
    schema = _simple_invoice_schema()
    value = {
        "invoice_id": "INV-1",
        "amount": 1,
        "currency": "USD",
        "items": [
            {"name": "apple", "price": 1.0},
            {"name": "banana", "price": 0.5},
        ],
    }
    result = validate_structured_output(value, schema)
    assert result.ok is True


def test_any_type_passes_anything():
    schema = {"type": "object", "properties": {"data": {"type": "any"}}, "additionalProperties": False}
    for v in [None, True, 1, 1.5, "x", [1, 2], {"a": 1}]:
        result = validate_structured_output({"data": v}, schema)
        assert result.ok is True, "failed for value: " + repr(v)


def test_null_type_passes_none():
    schema = {"type": "null"}
    assert validate_structured_output(None, schema).ok is True


def test_json_text_validation_passes():
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
    text = '{"a": "hello"}'
    result = validate_json_text_against_schema(text, schema)
    assert result.ok is True


# ── Failure cases ───────────────────────────────────────────────────────


def test_required_field_missing():
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
    result = validate_structured_output({}, schema)
    assert result.ok is False
    assert any(i.issue_type == "required_field_missing" for i in result.issues)


def test_type_mismatch_at_root():
    schema = {"type": "object"}
    result = validate_structured_output("not an object", schema)
    assert result.ok is False
    assert any(i.issue_type == "type_mismatch" and i.path == "$" for i in result.issues)


def test_type_mismatch_at_field():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
    result = validate_structured_output({"a": 42}, schema)
    assert result.ok is False
    assert any(i.issue_type == "type_mismatch" and i.path == "$.a" for i in result.issues)


def test_unknown_field_when_additional_properties_false():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "additionalProperties": False,
    }
    result = validate_structured_output({"a": "x", "b": 1}, schema)
    assert result.ok is False
    assert any(i.issue_type == "unknown_field" and i.path == "$.b" for i in result.issues)


def test_nested_required_field_missing():
    schema = {
        "type": "object",
        "properties": {
            "inner": {
                "type": "object",
                "required": ["k"],
                "properties": {"k": {"type": "string"}},
            }
        },
    }
    result = validate_structured_output({"inner": {}}, schema)
    assert result.ok is False
    assert any(i.path == "$.inner.k" for i in result.issues)


def test_nested_type_mismatch():
    schema = {
        "type": "object",
        "properties": {"inner": {"type": "object", "properties": {"k": {"type": "number"}}}},
    }
    result = validate_structured_output({"inner": {"k": "not-a-number"}}, schema)
    assert result.ok is False
    assert any(i.issue_type == "type_mismatch" and i.path == "$.inner.k" for i in result.issues)


def test_array_item_type_mismatch():
    schema = {"type": "array", "items": {"type": "string"}}
    result = validate_structured_output(["a", 1, "b"], schema)
    assert result.ok is False
    assert any(i.issue_type == "type_mismatch" and i.path == "$[1]" for i in result.issues)


def test_json_parse_failure():
    schema = {"type": "object"}
    result = validate_json_text_against_schema("{not valid json", schema)
    assert result.ok is False
    assert any(i.issue_type == "json_parse_failed" for i in result.issues)


def test_invalid_schema_unknown_type():
    schema = {"type": "quaternion"}
    result = validate_structured_output({}, schema)
    assert result.ok is False
    assert any(i.issue_type == "invalid_schema" for i in result.issues)


def test_invalid_schema_bad_required():
    schema = {"type": "object", "required": [123], "properties": {}}
    assert validate_schema_contract(schema)
    result = validate_structured_output({}, schema)
    assert result.ok is False
    assert any(i.issue_type == "invalid_schema" for i in result.issues)


def test_invalid_schema_bad_properties():
    schema = {"type": "object", "properties": "not-a-mapping"}
    assert validate_schema_contract(schema)
    result = validate_structured_output({}, schema)
    assert result.ok is False


def test_invalid_schema_bad_additional_properties():
    schema = {"type": "object", "additionalProperties": "yes"}
    assert validate_schema_contract(schema)
    result = validate_structured_output({}, schema)
    assert result.ok is False


# ── Type edge cases ─────────────────────────────────────────────────────


def test_bool_is_not_integer():
    schema = {"type": "integer"}
    assert validate_structured_output(True, schema).ok is False
    assert validate_structured_output(42, schema).ok is True


def test_bool_is_not_number():
    schema = {"type": "number"}
    assert validate_structured_output(False, schema).ok is False
    assert validate_structured_output(3.14, schema).ok is True
    assert validate_structured_output(42, schema).ok is True


def test_int_is_integer_and_number():
    assert validate_structured_output(1, {"type": "integer"}).ok is True
    assert validate_structured_output(1, {"type": "number"}).ok is True


def test_float_is_number_not_integer():
    assert validate_structured_output(1.5, {"type": "number"}).ok is True
    assert validate_structured_output(1.5, {"type": "integer"}).ok is False


def test_none_is_null():
    assert validate_structured_output(None, {"type": "null"}).ok is True
    assert validate_structured_output(0, {"type": "null"}).ok is False


def test_list_is_array_dict_is_object():
    assert validate_structured_output([], {"type": "array"}).ok is True
    assert validate_structured_output({}, {"type": "object"}).ok is True


def test_infer_json_type_labels():
    assert infer_json_type(None) == "null"
    assert infer_json_type(True) == "boolean"
    assert infer_json_type(False) == "boolean"
    assert infer_json_type(1) == "integer"
    assert infer_json_type(1.5) == "number"
    assert infer_json_type("x") == "string"
    assert infer_json_type([]) == "array"
    assert infer_json_type({}) == "object"


# ── Path tests ──────────────────────────────────────────────────────────


def test_root_path_is_dollar():
    result = validate_structured_output("x", {"type": "object"})
    assert any(i.path == "$" for i in result.issues)


def test_field_path_is_dotted():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
    result = validate_structured_output({"a": 1}, schema)
    assert any(i.path == "$.a" for i in result.issues)


def test_nested_object_path():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "object", "properties": {"b": {"type": "string"}}}},
    }
    result = validate_structured_output({"a": {"b": 1}}, schema)
    assert any(i.path == "$.a.b" for i in result.issues)


def test_array_item_path_is_indexed():
    schema = {"type": "array", "items": {"type": "string"}}
    result = validate_structured_output(["a", 1], schema)
    assert any(i.path == "$[1]" for i in result.issues)


def test_nested_array_object_path():
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}},
                },
            }
        },
    }
    result = validate_structured_output({"items": [{"name": "x"}, {"name": 42}]}, schema)
    assert any(i.path == "$.items[1].name" for i in result.issues)


# ── Serialization tests ────────────────────────────────────────────────


def test_issue_to_dict_stable():
    issue = StructuredSchemaIssue(
        issue_type="type_mismatch",
        path="$.x",
        expected="string",
        actual="number",
        detail="field x must be a string",
    )
    d = issue.to_dict()
    assert d["issue_type"] == "type_mismatch"
    assert d["path"] == "$.x"
    assert d["expected"] == "string"
    assert d["actual"] == "number"
    assert d["detail"] == "field x must be a string"


def test_issue_to_dict_only_required_fields_when_extra_none():
    issue = StructuredSchemaIssue(issue_type="required_field_missing", path="$.x")
    d = issue.to_dict()
    assert set(d.keys()) == {"issue_type", "path"}


def test_result_to_dict_round_trip():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
    result = validate_structured_output({"a": 1}, schema)
    rendered = json.loads(structured_schema_result_to_json(result))
    assert rendered["ok"] is False
    assert "issues" in rendered
    assert "checked_paths" in rendered
    assert "schema_hash" in rendered
    assert "value_hash" in rendered


def test_stable_json_hash_deterministic():
    value = {"b": 2, "a": 1, "c": [3, 1, 2]}
    h1 = stable_json_hash(value)
    h2 = stable_json_hash(value)
    h3 = stable_json_hash({"a": 1, "b": 2, "c": [3, 1, 2]})
    assert h1 == h2 == h3


def test_checked_paths_sorted_and_contains_root():
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"type": "object", "properties": {"name": {"type": "string"}}},
            }
        },
    }
    result = validate_structured_output(
        {"items": [{"name": "x"}, {"name": "y"}]}, schema
    )
    assert result.checked_paths == tuple(sorted(set(result.checked_paths)))
    assert "$" in result.checked_paths


def test_result_class_invariants():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
    result = validate_structured_output({"a": "x"}, schema)
    assert isinstance(result, StructuredSchemaValidationResult)
    assert result.ok is True
    assert isinstance(result.issues, tuple)
    assert isinstance(result.checked_paths, tuple)
    assert isinstance(result.schema_hash, str)
    assert isinstance(result.value_hash, str)


# ── Guardrail tests ────────────────────────────────────────────────────


GUARDRAIL_NEEDLES = (
    "mmap_optimizer.model",
    "mmap_optimizer.orchestration",
    "mmap_optimizer.optimizer",
    "mmap_optimizer.cli",
    "mmap_optimizer.scenario",
    "mmap_optimizer.core.scenario",
    "from mmap_optimizer.prompt.json_repair",
    "import json_repair",
    "jsonschema",
    "ast.literal_eval",
    "eval(",
    "open(",
)


@pytest.mark.parametrize("needle", GUARDRAIL_NEEDLES)
def test_no_forbidden_imports_or_calls(needle):
    assert needle not in MODULE_TEXT, "found forbidden needle: " + needle


def test_module_does_not_import_optimizer_or_cli_or_scenario_by_path_check():
    import ast

    tree = ast.parse(MODULE_TEXT)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    for name in imports:
        assert not name.startswith("mmap_optimizer.model"), name
        assert not name.startswith("mmap_optimizer.orchestration"), name
        assert not name.startswith("mmap_optimizer.cli"), name
        assert not name.startswith("mmap_optimizer.scenario"), name


def test_deterministic_across_calls():
    schema = _simple_invoice_schema()
    value = {"invoice_id": "INV-1", "amount": 19.99, "currency": "USD"}
    r1 = validate_structured_output(value, schema)
    r2 = validate_structured_output(value, schema)
    assert r1.ok == r2.ok
    assert r1.issues == r2.issues
    assert r1.checked_paths == r2.checked_paths
    assert r1.schema_hash == r2.schema_hash
    assert r1.value_hash == r2.value_hash


def test_validate_json_text_against_schema_rejects_non_str():
    with pytest.raises(TypeError):
        validate_json_text_against_schema(123, {"type": "object"})  # type: ignore[arg-type]


def test_validate_json_text_against_schema_does_not_use_repair_even_on_bad_text():
    # Just confirm parse failure doesn't crash and produces a clear issue.
    result = validate_json_text_against_schema("```json\n{}\n```", {"type": "object"})
    assert result.ok is False
    # The above string contains fence characters so json.loads fails directly.
    assert any(i.issue_type == "json_parse_failed" for i in result.issues)


def test_schema_contract_returns_tuple_of_strings():
    bad = {"type": "object", "required": [42]}
    contract = validate_schema_contract(bad)
    assert isinstance(contract, tuple)
    assert all(isinstance(x, str) for x in contract)
    assert len(contract) >= 1


def test_valid_schema_contract_is_empty_tuple():
    schema = _simple_invoice_schema()
    assert validate_schema_contract(schema) == ()


def test_non_json_serializable_value_stable_hash():
    class _NotJson:
        pass

    v = {"a": _NotJson()}
    h1 = stable_json_hash(v)
    h2 = stable_json_hash(v)
    assert h1 == h2


def test_result_to_json_is_stable():
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "additionalProperties": False}
    result = validate_structured_output({"a": 1}, schema)
    j1 = structured_schema_result_to_json(result)
    j2 = structured_schema_result_to_json(result)
    assert j1 == j2
    parsed = json.loads(j1)
    assert parsed["ok"] is True


def test_array_without_items_schema_allows_any_items():
    # If items is missing, array shape alone is checked (documented behavior).
    schema = {"type": "array"}
    assert validate_structured_output([1, "x", None], schema).ok is True
