# structured-output-schema-checker

## Purpose

Explicit, report-only schema contract checker for JSON-like outputs.

This utility answers a single question:

> Given a value already parsed into a Python dict / list / primitive,
> does it conform to a declared structural contract?

It performs **validation only** — no repair, no field addition, no
rename, no LLM call.

## Relation to json_repair

- [`json_repair`](json_repair_utility.md) turns raw text into a JSON
  body that is parseable by `json.loads`. It is a **text-level** tool.
- **`structured_output_schema`** validates a *parsed* value against a
  lightweight schema contract. It is a **structure-level** tool.

If your input is raw text, call `json_repair` first, then feed the
parsed result into `validate_structured_output`. Alternatively, use
`validate_json_text_against_schema`, which calls `json.loads` directly
and will NOT apply repair — parse failures become `json_parse_failed`
issues.

## Explicit invocation only

Nothing in this module is wired into the optimizer loop, CLI, or
scenario runner. It must be imported and called by a human caller.

```python
from mmap_optimizer.prompt.structured_output_schema import (
    validate_structured_output,
    validate_json_text_against_schema,
    structured_schema_result_to_json,
)
```

## Supported schema subset

Top-level keys (all optional unless noted):

| Key | Purpose |
|-----|---------|
| `type` (required) | ``object`` / ``array`` / ``string`` / ``number`` / ``integer`` / ``boolean`` / ``null`` / ``any`` |
| `required` | List of required field names for objects. |
| `properties` | Mapping of field name → nested schema for objects. |
| `additionalProperties` | `bool` — if `False`, unknown fields raise `unknown_field`. |
| `items` | Nested schema applied to every element of an array. |

Example:

```python
schema = {
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
```

## Supported types

| Type | Accepts |
|------|---------|
| `object` | `dict` |
| `array` | `list` |
| `string` | `str` |
| `number` | `int` or `float`, but **not** `bool` |
| `integer` | `int`, but **not** `bool` |
| `boolean` | `bool` |
| `null` | `None` |
| `any` | anything |

## Path format

- Root: ``$``
- Field access: ``$.field``
- Nested field: ``$.a.b.c``
- Array index: ``$[0]``, ``$[1]``
- Mixed: ``$.items[0].name``

## Examples

```python
result = validate_structured_output(
    {"invoice_id": "INV-1", "amount": 19.99, "currency": "USD"},
    schema,
)
# result.ok is True; result.issues is empty.
```

```python
result = validate_structured_output(
    {"invoice_id": 42, "amount": 19.99},  # missing currency, wrong type
    schema,
)
# result.ok is False; issues include required_field_missing and type_mismatch.
```

```python
text = '{"invoice_id": "INV-1", "amount": 19.99, "currency": "USD"}'
result = validate_json_text_against_schema(text, schema)
# result.ok is True.
```

## Invalid schema behavior

`validate_schema_contract(schema)` returns a tuple of human-readable
issue strings describing problems in the schema itself. Empty tuple
means the schema contract is well-formed.

`validate_structured_output` never raises on a malformed schema — it
returns `ok=False` with a single `invalid_schema` issue at path `$`.

## JSON text validation behavior

`validate_json_text_against_schema(text, schema)` calls `json.loads`
exactly once. If parsing fails, `ok=False` with a `json_parse_failed`
issue is returned. **No JSON repair is performed automatically.**

## Limitations

- Only a subset of JSON Schema is supported (see above).
- No `oneOf` / `anyOf` / `allOf`.
- No `minLength` / `maxLength`, `minimum` / `maximum`, `minItems` /
  `maxItems`, `pattern`, `format`, or other value constraints.
- No external `jsonschema` dependency — ever.

## Guardrails

- No LLM call.
- No import of `mmap_optimizer.model.*`, `mmap_optimizer.cli.*`,
  `mmap_optimizer.scenario.*`, or `mmap_optimizer.orchestration.*`.
- No filesystem writes.
- No `eval` / `ast.literal_eval`.
- No `jsonschema` dependency.
- Deterministic output — same inputs always produce identical results.

## Test coverage

See `tests/test_structured_output_schema_checker.py`. Coverage
includes:

- Success cases (flat object, nested object, arrays, `any`, `null`, JSON text).
- Failure cases (required field missing, type mismatch, unknown
  field, nested issues, array item issues, parse failure, invalid
  schema).
- Type edge cases (`bool` vs `int` vs `float` vs `None`).
- Path format tests (root, field, nested object, array index, mixed).
- Serialization stability (`to_dict`, `to_json`, hash deterministic,
  `checked_paths` sorted).
- Guardrail tests (no LLM / optimizer / CLI / scenario / repair /
  `jsonschema` imports or calls).
