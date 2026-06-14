# Scenario-Gated Prompt Utility Runner

**Module:** `mmap_optimizer.prompt.utility_runner`

**Purpose:** An explicit-call orchestrator that runs one or more pre-existing
prompt utilities against an original/rewritten text pair and returns a
structured, JSON-serializable report. It is the report-only entry point for
humans, CI pipelines, or future scenario workflows who want to audit prompt
rewrites without modifying anything.

---

## Why "Scenario-Gated"?

The word "gated" reflects the design constraint: utilities are only executed
when the caller explicitly passes `enabled=True`. The default is `enabled=False`
so that no utility runs unless explicitly opted in. This is intentional —
the runner is a tool for deliberate, manual invocation, not an automatic
optimizer-loop hook.

---

## Relation to Explicit Utilities

This module composes pre-existing explicit utilities, including the structured output schema checker added in PR #60:

| Utility name | Module | Purpose |
|---|---|---|
| `rewrite_safety` | `mmap_optimizer.prompt.rewrite_safety` | Composed safety report (JSON repair + numbering + immutable payload + audit) |
| `json_repair` | `mmap_optimizer.prompt.json_repair` | Strip fences, remove prose, fix trailing commas |
| `numbering_refactor` | `mmap_optimizer.prompt.numbering_refactor` | Detect and normalize heading/list/step numbering |
| `immutable_payload` | `mmap_optimizer.prompt.immutable_payload` | Validate placeholder/field structural integrity |
| `audit_checklist` | `mmap_optimizer.prompt.audit_checklist` | Structured audit checklist report |
| `structured_schema` | `mmap_optimizer.prompt.structured_output_schema` | Validate JSON-like text against a lightweight schema contract |

**Default enabled:** `false`. Nothing in the optimizer imports this module.

---

## Default Safety Behavior

```
PromptUtilityRunConfig()  # all defaults

→ enabled=False
→ report_only=True
→ utilities=()
→ nothing runs
→ result.enabled=False
→ result.ok=True
→ result.reports={}
```

This means a caller that accidentally constructs the default config
(e.g. forgetting to set `enabled=True`) will safely get an empty result
with `ok=True` and a warning issue, rather than silently running utilities.

---

## Report-Only Behavior

`report_only=True` (the default) means:

- `original` and `rewritten` are never modified
- No file is written to disk
- No repair is applied to any production prompt
- No utility output is written anywhere
- Only an in-memory `PromptUtilityRunResult` is returned

---

## Explicit Invocation Only

The caller must import and invoke the utility explicitly. Typical flow:

```python
from mmap_optimizer.prompt.utility_runner import (
    PromptUtilityRunConfig,
    PromptUtilityRunResult,
    run_prompt_utilities,
    render_prompt_utility_run_summary,
    prompt_utility_run_result_to_json,
)

config = PromptUtilityRunConfig(
    enabled=True,
    utilities=("rewrite_safety", "json_repair"),
    apply_json_repair=True,
    apply_numbering_refactor=True,
    report_only=True,
    protected_placeholders=("answer", "question"),
    metadata={"author": "human-reviewer"},
)

result = run_prompt_utilities(
    target_id="prompt-v3-to-v4",
    original=original_prompt_text,
    rewritten=candidate_rewrite_text,
    config=config,
)

if not result.ok:
    print(render_prompt_utility_run_summary(result))

# Serialize for CI / audit log:
json_str = prompt_utility_run_result_to_json(result, sort_keys=True)
```

---

## Supported Utilities

| Name | Description |
|---|---|
| `rewrite_safety` | Full composed report (JSON repair + numbering + immutable payload + audit) |
| `json_repair` | Standalone JSON repair on `rewritten`; does not feed into other utilities |
| `numbering_refactor` | Standalone numbering detection and normalization on `rewritten` |
| `immutable_payload` | Standalone immutable payload validation of `original` vs `rewritten` |
| `audit_checklist` | Minimal runner-level audit (runner enabled, report_only, known utilities) |
| `structured_schema` | Schema contract validation against `rewritten`, `original`, or `json_repair` output. Requires `structured_schema` mapping in config. |

**Unknown utility names** cause `ok=False` and are listed in `issues`.

**Duplicate utility names** cause a validation issue (but are not executed twice).

---

## API

| Symbol | Purpose |
|---|---|
| `PromptUtilityRunConfig` | Frozen dataclass — `enabled`, `utilities`, `apply_json_repair`, `apply_numbering_refactor`, `report_only`, `protected_placeholders`, `metadata`, `structured_schema`, `structured_schema_input` |
| `PromptUtilityRunResult` | Frozen dataclass — `target_id`, `enabled`, `report_only`, `utilities`, `ok`, `reports`, `issues`, `metadata` |
| `run_prompt_utilities(*, target_id, original, rewritten, config)` | Primary entry point. Returns `PromptUtilityRunResult` |
| `validate_prompt_utility_run_config(config)` | Validate config, return tuple of issue strings |
| `prompt_utility_run_result_to_json(result, *, indent=2, sort_keys=False)` | Serialize result to JSON string |
| `prompt_utility_run_result_from_dict(data)` | Reconstruct result from dict (inverse of `result.to_dict()`) |
| `render_prompt_utility_run_summary(result)` | Plain-text human-readable summary |

### PromptUtilityRunConfig schema

```python
@dataclass(frozen=True)
class PromptUtilityRunConfig:
    enabled: bool = False           # Must be True to run anything
    utilities: tuple[str, ...] = () # Utility names to execute
    apply_json_repair: bool = False # Forwarded to rewrite_safety
    apply_numbering_refactor: bool = True  # Forwarded to rewrite_safety
    report_only: bool = True        # No writes, no applies
    protected_placeholders: tuple[str, ...] = ()  # Forwarded to utilities
    metadata: Mapping[str, Any] | None = None  # Caller-supplied context
    structured_schema: Mapping[str, Any] | None = None  # Schema contract
    structured_schema_input: str = "rewritten"  # "rewritten" | "original" | "json_repair"
```

### PromptUtilityRunResult schema

```python
@dataclass(frozen=True)
class PromptUtilityRunResult:
    target_id: str                       # e.g. "prompt-v3-to-v4"
    enabled: bool                         # True iff runner was enabled
    report_only: bool                     # True iff report-only mode
    utilities: tuple[str, ...]            # Utilities requested
    ok: bool                              # True unless validation/utility failure
    reports: dict[str, Any]              # Utility name → report dict
    issues: tuple[str, ...]              # Human-readable issue strings
    metadata: dict[str, Any]             # Caller-supplied context
```

---

## Examples

### 1. Disabled default (no-op)

```python
result = run_prompt_utilities(
    target_id="t",
    original=original_text,
    rewritten=rewritten_text,
    config=PromptUtilityRunConfig(),  # enabled=False
)
# result.enabled = False
# result.ok = True
# result.reports = {}
```

### 2. Run rewrite_safety only

```python
config = PromptUtilityRunConfig(
    enabled=True,
    utilities=("rewrite_safety",),
    apply_json_repair=False,  # default
    apply_numbering_refactor=True,  # default
)
result = run_prompt_utilities(
    target_id="prompt-v3",
    original=original_text,
    rewritten=rewritten_text,
    config=config,
)
# result.reports["rewrite_safety"] contains the full safety report
```

### 3. Run json_repair + rewrite_safety

```python
config = PromptUtilityRunConfig(
    enabled=True,
    utilities=("json_repair", "rewrite_safety"),
    apply_json_repair=True,  # enables JSON repair inside rewrite_safety
)
result = run_prompt_utilities(
    target_id="prompt-v3",
    original=original_text,
    rewritten='```json\n{"a":1}\n```',
    config=config,
)
# result.reports["json_repair"] — standalone JSON repair report
# result.reports["rewrite_safety"] — includes JSON repair stage
```

### 4. Run immutable_payload only

```python
config = PromptUtilityRunConfig(
    enabled=True,
    utilities=("immutable_payload",),
)
result = run_prompt_utilities(
    target_id="payload-check",
    original=original_text,
    rewritten=rewritten_text,
    config=config,
)
# result.reports["immutable_payload"]
```

### 5. Validate rewritten JSON against a schema

```python
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
config = PromptUtilityRunConfig(
    enabled=True,
    utilities=("structured_schema",),
    structured_schema=schema,
    structured_schema_input="rewritten",
)
result = run_prompt_utilities(
    target_id="invoice-json-check",
    original="orig",
    rewritten='{"invoice_id": "INV-1", "amount": 19.99, "currency": "USD"}',
    config=config,
)
# result.reports["structured_schema"]["ok"] is True if the JSON conforms
```

### 6. Combine json_repair + structured_schema

```python
config = PromptUtilityRunConfig(
    enabled=True,
    utilities=("json_repair", "structured_schema"),
    structured_schema=schema,
    structured_schema_input="json_repair",
)
result = run_prompt_utilities(
    target_id="invoice-json-check",
    original="orig",
    rewritten='```json\n{"invoice_id": "INV-1", "amount": 1, "currency": "USD"}\n```',
    config=config,
)
# result.reports["json_repair"] — JSON repair stage result
# result.reports["structured_schema"] — schema validation against repaired_text
```

### 7. Combine rewrite_safety + structured_schema

```python
config = PromptUtilityRunConfig(
    enabled=True,
    utilities=("rewrite_safety", "structured_schema"),
    structured_schema=schema,
)
result = run_prompt_utilities(
    target_id="prompt-v3-to-v4",
    original=original_text,
    rewritten=rewritten_text,
    config=config,
)
# result.reports["rewrite_safety"] — the full safety report
# result.reports["structured_schema"] — schema validation against rewritten
```

---

## `ok` Semantics

`ok` is `True` unless one of the following occurs:

| Condition | Effect |
|---|---|
| Unknown utility name | `ok=False`, issue: `"unknown utility: X"` |
| Duplicate utility name | `ok=False`, issue: `"duplicate utility name: X"` |
| `rewrite_safety` report `ok=False` | `ok=False`, issue with overall_status |
| `json_repair` standalone `ok=False` | `ok=False`, issue with issue count |
| `immutable_payload` `ok=False` | `ok=False`, issue with issue count |
| `audit_checklist` `overall_status="fail"` | `ok=False` |
| `structured_schema` requested but schema missing or non-mapping | `ok=False`, issue: `"structured_schema: missing or non-mapping schema (got ...)"` |
| `structured_schema_input` not in `{rewritten, original, json_repair}` | `ok=False`, issue: `"invalid structured_schema_input: ..."` |
| `structured_schema_input="json_repair"` but `json_repair` utility not listed | `ok=False`, issue: `"structured_schema: json_repair input requested but json_repair utility is not in utilities list"` |
| `structured_schema` validation `ok=False` | `ok=False`, issue with issue count |
| `structured_schema` with an invalid schema contract (e.g. bad `type`) | `ok=False`, invalid-schema issue |

**`enabled=False` never causes `ok=False`** — it returns `ok=True` with a
warning issue about the runner being disabled.

---

## `report_only` Semantics

When `report_only=True` (the default):

- `original` and `rewritten` are never mutated
- No file is written
- `normalized_text` from `numbering_refactor` is only in the report dict,
  not applied to any production text
- `repaired_text` from `json_repair` is only in the report dict,
  not propagated to other utilities (except `rewrite_safety`, which has its
  own `apply_json_repair` flag)

---

## Limitations

1. **This is not an optimizer loop.** It does not run automatically. Callers
   must import and invoke it explicitly.
2. **`normalized_text` is for display only.** `numbering_refactor`'s
   `normalized_text` in the report is informational — it is not applied
   to any file or passed to other utilities (except through `rewrite_safety`
   when `apply_numbering_refactor=True`).
3. **`json_repair` standalone does not feed other utilities.** When running
   `json_repair` alone, its `repaired_text` stays in the report dict and is
   not forwarded to `immutable_payload` or `numbering_refactor`. Use
   `rewrite_safety` with `apply_json_repair=True` for composed behavior.
4. **Unknown utilities cause failure.** There is no silent fallback for unknown
   utility names. Callers must ensure they only pass known names.
5. **This module does not write files.** Report serialization (`to_json`)
   produces a string — the caller is responsible for writing it to disk if
   desired.

---

## Safety Guardrails

1. **`enabled=False` by default.** Nothing runs without explicit opt-in.
2. **`report_only=True` by default.** No writes, no applies.
3. **No LLM call.** Zero dependency on `mmap_optimizer.model.*`.
4. **No optimizer loop change.** Nothing calls this module automatically.
5. **No CLI integration.** No CLI flags reference this module.
6. **No scenario integration.** No scenario code reads or writes the report.
7. **Frozen dataclass output.** Results are immutable once built.
8. **Deterministic.** Same inputs always produce identical outputs.
9. **TypeError for non-str inputs.** Protects against accidental numeric or
   None input.
10. **No eval / ast.literal_eval.** JSON parsing uses `json.loads` only.
11. **`enabled=False` never fails.** A disabled runner always returns
    `ok=True` even if unknown utilities are named.

---

## Test Coverage

Tests live in
[tests/test_prompt_utility_runner.py](file:///workspace/tests/test_prompt_utility_runner.py)
and cover 45+ test cases across the following areas:

- Default behavior (disabled, report_only, no-op, original/rewritten unchanged)
- Config validation (unknown utility, duplicate, TypeError)
- Utility execution (each of the 5 utilities runs independently; multiple utilities)
- Report-only guarantees (no mutation, no filesystem writes)
- Serialization (to_dict, to_json, from_dict round-trip, summary rendering)
- Failure semantics (ok=False on utility failure, disabled unknown utility does not fail)
- Guardrails (no forbidden imports, no eval/literal_eval, deterministic)

Run:

```bash
python -m pytest tests/test_prompt_utility_runner.py -q
```
