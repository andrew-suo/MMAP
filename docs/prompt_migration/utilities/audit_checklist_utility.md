# Audit-Checklist Utility

**Module:** `mmap_optimizer.prompt.audit_checklist`

**Purpose:** Provide deterministic data structures and helpers for building,
validating, and serializing structured audit-checklist reports. These reports
serve as machine-readable + human-readable audit artifacts for prompt rewrite,
compression, repair, patch generation, and evaluation stages.

This utility is the **explicit-call** companion to the
[audit-checklist pattern](../pattern_library/audit_checklist_pattern.md).

---

## Relation to Pattern Library

- **Pattern:** audit-checklist pattern (see
  `../pattern_library/audit_checklist_pattern.md`)
- **Utility module:** `mmap_optimizer.prompt.audit_checklist`
- **Default enabled:** **false** *(nothing calls this utility automatically)*
- **Explicit invocation only:** callers must import and call the API manually.
- **No LLM call:** the utility works only on dataclass / dict structures —
  it does not call any model and has no dependency on
  `mmap_optimizer.model.*` or `mmap_optimizer.orchestration.*`.

---

## Explicit invocation only

The utility is intentionally **NOT** wired into the optimizer loop. An audit
must be triggered *explicitly* by the caller. Example:

```python
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

# Structural validation before using the report.
issues = validate_audit_checklist_report(report)
if issues:
    print("Report has structural issues:", issues)

# Human-readable output.
print(render_audit_checklist_summary(report))

# Machine-readable JSON for storage / CI.
from mmap_optimizer.prompt.audit_checklist import audit_checklist_to_json
print(audit_checklist_to_json(report))
```

---

## Default enabled: false

- `mmap_optimizer.prompt.audit_checklist` is never imported by default from
  any optimizer loop / CLI / scenario code.
- `tests/test_prompt_audit_checklist_utility.py` is the only consumer.

---

## API

| Symbol | Purpose |
|---|---|
| `AuditChecklistItem` | Frozen dataclass; one audit dimension result. |
| `AuditChecklistReport` | Frozen dataclass; complete audit report. |
| `build_audit_checklist_report(*, target_id, items, metadata=None)` | Primary builder; normalizes inputs, derives `overall_status`, auto-generates `failure_summary` / `repair_recommendation`. |
| `validate_audit_checklist_report(report)` | Returns `tuple[str, ...]` of structural issues; empty = valid. |
| `audit_checklist_to_json(report, *, indent=2, sort_keys=False)` | Serializes to a JSON string. |
| `audit_checklist_from_dict(data)` | Reconstructs a report from a dict (inverse of `to_dict`). |
| `render_audit_checklist_summary(report)` | Plain-text human-readable summary. |

---

## Item schema

```
AuditChecklistItem(
    id: str                    # unique identifier for this item
    dimension: str             # audit dimension name
    status: str                # "pass" | "warning" | "fail"
    evidence: str              # observed fact / measurement
    issue: str | None          # problem description (required for warning/fail)
    severity: str = "info"     # "blocker" | "major" | "minor" | "info"
    suggested_fix: str | None # recommended fix (optional)
)
```

All string fields accept any content. Status and severity are normalized to
lowercase automatically.

---

## Report schema

```
AuditChecklistReport(
    target_id: str                               # what is being audited
    overall_status: str                           # "pass" | "warning" | "fail"
    items: tuple[AuditChecklistItem, ...]        # ordered checklist items
    failure_summary: str | None                   # auto-generated from fail items
    repair_recommendation: str | None             # auto-generated from items with suggested_fix
    metadata: dict[str, Any] = {}                # caller-supplied arbitrary metadata
)
```

`items` is always a `tuple` (deterministic, immutable).

---

## Status semantics

| Status | Meaning |
|---|---|
| `pass` | The dimension passed the audit. **Requires** non-empty `evidence`. |
| `warning` | The dimension has a concern that should be noted. **Requires** non-empty `issue`. |
| `fail` | The dimension has a defect that must be addressed. **Requires** non-empty `issue`. |

`overall_status` is auto-derived: `fail` > `warning` > `pass`.

---

## Severity semantics

| Severity | Meaning |
|---|---|
| `blocker` | Must block use; no workaround. |
| `major` | Significant defect; must be fixed before use. |
| `minor` | Acceptable with a known caveat; should be tracked. |
| `info` | Informational observation; no action required. |

---

## Evidence requirements

- **`status=pass`:** `evidence` must be non-empty. A passing item without
  evidence is structurally invalid.
- **`status=warning` / `status=fail`:** `issue` must be non-empty.
- **`severity=blocker` / `severity=major`:** `suggested_fix` is strongly
  recommended for auto-generation of `repair_recommendation`.

---

## Read-only audit guardrail

This utility **only generates report structures** — it does not:

- ❌ receive a rewritten text and return a rewritten text
- ❌ perform any repair
- ❌ apply patches
- ❌ rewrite prompts
- ❌ call any LLM

`repair_recommendation` is a string field containing a *suggested* fix;
the caller decides whether and how to act on it.

---

## Examples

### Basic audit

```python
from mmap_optimizer.prompt.audit_checklist import (
    AuditChecklistItem, build_audit_checklist_report,
)

report = build_audit_checklist_report(
    target_id="patch-v7-to-v8",
    items=[
        AuditChecklistItem(
            id="placeholder-count",
            dimension="placeholder_preservation",
            status="pass",
            evidence="8 placeholders in original, 8 in rewritten.",
        ),
        AuditChecklistItem(
            id="constraint-integrity",
            dimension="constraint_preservation",
            status="fail",
            evidence="Rewritten removed 'DO NOT' clause.",
            issue="Safety constraint dropped during compression.",
            severity="blocker",
            suggested_fix='Re-add: "DO NOT generate labels not present in the image."',
        ),
    ],
    metadata={"operator": "compression-v2"},
)
```

### Dict-based construction

```python
items = [
    {
        "id": "output-schema",
        "dimension": "output_schema",
        "status": "PASS",
        "evidence": '{"answer": "...", "confidence": "..."} still valid.',
        "issue": None,
        "severity": "MINOR",
        "suggested_fix": None,
    },
]
report = build_audit_checklist_report(target_id="prompt-v4", items=items)
```

### Validation before use

```python
from mmap_optimizer.prompt.audit_checklist import validate_audit_checklist_report

issues = validate_audit_checklist_report(report)
if issues:
    print("Refusing to use invalid report:")
    for issue in issues:
        print(" -", issue)
    # Alternatively: raise ValueError(issues)
```

---

## Issue taxonomy / common dimensions

The following dimensions are documented as common audit targets but are **not
enforced** by the utility (any string is accepted as a dimension name).

| Dimension | Typical concern |
|---|---|
| `completeness` | All required sections / rules present |
| `constraint_preservation` | Hard constraints survived rewriting |
| `ambiguity_reduction` | Vague language has been tightened |
| `output_schema` | JSON / structured output format unchanged |
| `placeholder_preservation` | All `{placeholders}` intact |
| `payload_integrity` | Business content unchanged |
| `format_validity` | Markdown / markup syntax valid |
| `semantic_risk` | No unintended semantic shift |
| `safety_compliance` | No harmful content introduced |

---

## Limitations

1. **Not a semantic evaluator.** The utility only structures audit results;
   it does not assess whether a prompt is "good" — callers supply the
   dimension judgments.
2. **No automatic scoring.** `overall_status` is binary/fuzzy (pass/warning/
   fail), not a numeric score. For numeric scoring, callers can compute
   their own score from `items` and store it in `metadata`.
3. **Metadata JSON-safety check is shallow.** Only `json.dumps` is used;
   highly nested structures with custom encoders may still fail at
   serialization time.
4. **Suggested fix is advisory only.** The `suggested_fix` field is a
   string — it does not describe how to apply the fix.

---

## Safety guardrails

1. **No LLM call.** The module has zero model / orchestration dependencies.
2. **No default integration.** Nothing in the codebase calls this utility
   automatically.
3. **TypeError on bad input.** `build_audit_checklist_report(target_id=42, ...)`
   raises `TypeError` — it does not silently cast to string.
4. **Frozen dataclasses.** `AuditChecklistItem` and `AuditChecklistReport` are
   immutable; reports cannot be accidentally mutated after construction.
5. **Validation before use.** `validate_audit_checklist_report` returns issues
   as a tuple — callers can check `len(issues) == 0` or inspect individual
   messages.
6. **JSON-serializable.** `to_dict` / `audit_checklist_to_json` work for
   storage, CI pipelines, and logging.
7. **Deterministic.** Same inputs always produce identical outputs.

---

## Test coverage

Tests live in
[tests/test_prompt_audit_checklist_utility.py](file:///workspace/tests/test_prompt_audit_checklist_utility.py)
and cover:

- construction: dataclass + dict items, status/severity normalization,
  overall_status derivation (all-pass / any-warning / any-fail),
  failure_summary, repair_recommendation, input-dict immutability (10 tests)
- validation: empty target_id, empty items, empty/duplicate id, empty
  dimension, invalid status/severity, pass-without-evidence,
  warning/fail-without-issue, overall_status mismatch,
  JSON-unsafe metadata, valid report returns empty tuple (11 tests)
- serialization: item.to_dict, report.to_dict, to_json, sort_keys
  determinism, from_dict round-trip, items-is-tuple, JSON round-trip
  (7 tests)
- rendering: target_id, overall_status, fail/warning/pass counts,
  severity counts, repair_recommendation (5 tests)
- guardrails: TypeError, deterministic, empty-metadata stability,
  AST-level import check, from_dict rejects bad input (8 tests)

Run:

```bash
python -m pytest tests/test_prompt_audit_checklist_utility.py -q
```
