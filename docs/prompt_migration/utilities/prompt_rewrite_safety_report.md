# Prompt Rewrite Safety Report Utility

**Module:** `mmap_optimizer.prompt.rewrite_safety`

**Purpose:** A deterministic wrapper that combines four previously-shipped
explicit utilities into a single structured *safety report* for prompt
rewrites. Given an `original` prompt text and a `rewritten` prompt text, it
produces a `PromptRewriteSafetyReport` containing:

- **JSON repair** (optional)   (via `mmap_optimizer.prompt.json_repair`)
- **numbering** analysis        (via `mmap_optimizer.prompt.numbering_refactor`)
- **immutable-payload** analysis (via `mmap_optimizer.prompt.immutable_payload`)
- **audit-checklist** consolidation (via `mmap_optimizer.prompt.audit_checklist`)

This utility is the **explicit-call** companion to four existing pattern
utilities. It is never wired into the optimizer loop, CLI, or any scenario.

---

## Relation to Pattern Library

| Pattern | Companion utility |
|---|---|
| json-repair-position-valid | `mmap_optimizer.prompt.json_repair` |
| numbering-only-refactor | `mmap_optimizer.prompt.numbering_refactor` |
| immutable-payload | `mmap_optimizer.prompt.immutable_payload` |
| audit-checklist | `mmap_optimizer.prompt.audit_checklist` |

**Default enabled:** `false`. Nothing in the optimizer imports this module.

---

## Explicit invocation only

The caller must import and invoke the utility themselves. Typical flow:

```python
from mmap_optimizer.prompt.rewrite_safety import (
    build_prompt_rewrite_safety_report,
    render_prompt_rewrite_safety_summary,
    prompt_rewrite_safety_report_to_json,
)

report = build_prompt_rewrite_safety_report(
    target_id="prompt-v3-to-v4",
    original=original_prompt_text,
    rewritten=candidate_rewrite_text,
    apply_numbering_refactor=True,
    apply_json_repair=False,  # Default: False — must explicitly enable
    protected_placeholders=None,  # let immutable-payload auto-detect
    metadata={"author": "human-reviewer", "round": 7},
)

if not report.ok:
    print(render_prompt_rewrite_safety_summary(report))

# For CI / audit logging:
with open("safety-report.json", "w") as f:
    f.write(prompt_rewrite_safety_report_to_json(report, sort_keys=True))
```

### apply_numbering_refactor semantics

- `True` (default): the rewritten text is passed through
  `refactor_prompt_numbering_only`, and the result is stored in
  `report.normalized_rewritten`. The original hash, the rewritten hash, and
  the normalized hash are all stored for traceability.
- `False`: no numbering normalization is performed; `normalized_rewritten`
  equals the input text (after optional JSON repair), and the utility still
  performs immutable-payload and audit analysis.

### apply_json_repair semantics

- `False` (default): no JSON repair is performed. This preserves backward
  compatibility with existing callers.
- `True`: the rewritten text is passed through `repair_json_output` before
  numbering normalization. If repair succeeds, the repaired text is used for
  subsequent steps. If repair fails, the report is marked `ok=False` and
  `overall_status="fail"`, but the report is still generated (no exception).

---

## Pipeline order

When `apply_json_repair=True`:

```
rewritten
    ↓ repair_json_output(rewritten)
    ↓ json_repaired_text
    ↓ refactor_prompt_numbering_only(json_repaired_text) if apply_numbering_refactor
    ↓ normalized_rewritten
    ↓ validate_immutable_payload(original, normalized_rewritten)
    ↓ build_audit_checklist_report(...)
```

When `apply_json_repair=False`:

```
rewritten
    ↓ refactor_prompt_numbering_only(rewritten) if apply_numbering_refactor
    ↓ normalized_rewritten
    ↓ validate_immutable_payload(original, normalized_rewritten)
    ↓ build_audit_checklist_report(...)
```

---

## API

| Symbol | Purpose |
|---|---|
| `build_prompt_rewrite_safety_report(*, target_id, original, rewritten, apply_numbering_refactor=True, apply_json_repair=False, protected_placeholders=None, metadata=None)` | Primary entry point. Returns a `PromptRewriteSafetyReport`. |
| `PromptRewriteSafetyReport` | Frozen dataclass with 17 fields (see below). |
| `prompt_rewrite_safety_report_to_json(report, *, indent=2, sort_keys=False)` | Serialize to JSON. |
| `prompt_rewrite_safety_report_from_dict(data)` | Reconstruct a report from a plain dict (inverse of `report.to_dict()`). Handles legacy dicts without JSON repair fields. |
| `render_prompt_rewrite_safety_summary(report)` | Plain-text human-readable summary. |

### PromptRewriteSafetyReport schema

```python
@dataclass(frozen=True)
class PromptRewriteSafetyReport:
    target_id: str                        # e.g. "prompt-v3-to-v4"
    ok: bool                               # True iff overall == pass + payload intact + JSON repair ok
    overall_status: str                    # "pass" | "warning" | "fail"
    original_hash: str                     # SHA-256 of original
    rewritten_hash: str                    # SHA-256 of rewritten
    json_repaired_hash: str | None         # SHA-256 after JSON repair (if applied and succeeded)
    normalized_rewritten_hash: str         # SHA-256 after numbering-refactor
    numbering_issue_count: int             # issues from detect_numbering_issues
    immutable_payload_issue_count: int     # issues from validate_immutable_payload
    audit_issue_count: int                 # items in audit_report with status != pass
    json_repair_applied: bool              # True iff apply_json_repair=True was passed
    json_repair_ok: bool | None            # True/False if repair applied; None otherwise
    json_repair_issue_count: int           # issues from JSON repair; 0 if not applied
    json_repaired_text: str | None         # repaired text if repair applied and succeeded
    normalized_rewritten: str              # post-refactor rewrite text
    audit_report: AuditChecklistReport     # inner audit report (3-4 items)
    metadata: dict[str, Any]               # caller-supplied context
```

---

## Audit item semantics

The inner `audit_report` contains 3 items when `apply_json_repair=False`,
and 4 items when `apply_json_repair=True`:

| id | dimension | when it flags |
|---|---|---|
| `json-repair` | `format_validity` | (Only present when `apply_json_repair=True`) JSON repair succeeded with changes → warning/minor; JSON repair succeeded without changes → pass/info; JSON repair failed → fail/blocker. |
| `payload_integrity` | `payload_integrity` | The payload validation fails; any placeholder renames, field renames, heading deletions, new rules, etc. |
| `format_validity` | `format_validity` | Numbering issues were detected in the rewritten text; warning if `apply_numbering_refactor=True` since refactor output is provided; warning if `False` and numbering defects remain; pass otherwise. |
| `rewrite_traceability` | `format_validity` | Reports hash chain: rewritten → json_repaired (if present) → normalized-rewritten. If any transformation occurred, flags as warning with all hashes in evidence. |

### `ok` vs. `overall_status`

- `ok` is True **only when** `overall_status != "fail"` **and** the
  immutable-payload check reported zero issues **and** (if JSON repair was
  applied) it succeeded. This is a conservative gate: a numbering-only
  rewrite (payload-preserved) will produce `ok=True` but
  `overall_status="warning"`; callers can inspect `overall_status` for finer
  granularity.
- `overall_status` mirrors the status aggregation logic of the underlying
  audit-checklist report: `fail` wins over `warning`, which wins over `pass`.

---

## Hash traceability

The report includes a full hash chain for traceability:

- `original_hash`: SHA-256 of the original text.
- `rewritten_hash`: SHA-256 of the rewritten text (before any transformation).
- `json_repaired_hash`: SHA-256 of the repaired text (if `apply_json_repair=True` and repair succeeded).
- `normalized_rewritten_hash`: SHA-256 of the final normalized text.

When transformations occur:
- `rewritten_hash != json_repaired_hash` indicates JSON repair modified the text.
- `json_repaired_hash != normalized_rewritten_hash` indicates numbering refactor modified the text.

---

## Failure behavior

When `apply_json_repair=True` and JSON repair fails:

- **No exception is thrown.** The report is still generated.
- `normalized_rewritten` is set to the original `rewritten` text (no repair applied).
- `ok` is `False`.
- `overall_status` is `"fail"`.
- The `json-repair` audit item has `status="fail"` and `severity="blocker"`.
- `json_repaired_text` is `None`.
- `json_repaired_hash` is `None`.

This allows callers to inspect the failure details without handling exceptions.

---

## Examples

### Without JSON repair (default)

```text
Original:      ## Instructions\n1. Read {question}\n2. Emit {answer}\n
Rewritten:     ## Instructions\n1. Read {question}\n1. Emit {answer}\n
apply_json_repair: False (default)
```

This produces:

- `numbering_issue_count > 0` (list numbering detected)
- `immutable_payload_issue_count == 0` (placeholders preserved)
- `ok = True`, `overall_status = "warning"`
- `rewritten_hash != normalized_rewritten_hash` (reflects the refactor)
- `json_repair_applied = False`
- `json_repair_ok = None`

### With JSON repair (success)

```text
Original:      {"a": 1}
Rewritten:     ```json\n{"a": 1}\n```
apply_json_repair: True
```

This produces:

- `json_repair_applied = True`
- `json_repair_ok = True`
- `json_repair_issue_count > 0` (fence removed)
- `json_repaired_text = '{"a": 1}'`
- `json_repaired_hash != rewritten_hash`
- `ok = True`, `overall_status = "warning"` (repair changed text)
- `json-repair` audit item: `status="warning"`, `severity="minor"`

### With JSON repair (failure)

```text
Original:      {"a": 1}
Rewritten:     {"a":  (truncated JSON)
apply_json_repair: True
```

This produces:

- `json_repair_applied = True`
- `json_repair_ok = False`
- `json_repaired_text = None`
- `json_repaired_hash = None`
- `normalized_rewritten = '{"a":'` (original rewritten, no repair)
- `ok = False`, `overall_status = "fail"`
- `json-repair` audit item: `status="fail"`, `severity="blocker"`
- `suggested_fix = "Produce position-valid JSON before safety validation."`

---

## Limitations

1. **Semantic analysis is out of scope.** The utility compares text, not
   meaning. A rewrite that rewords a rule without changing its numbering or
   placeholder surface will be considered payload-preserving.
2. **Numbering detection is deterministic but limited.** It handles heading
   numbers (## 1. / ## 2.), ordered list (1./2./3.), and `Step N` patterns.
   Arbitrary custom numbering conventions are not detected.
3. **Placeholder regex covers one form.** The placeholder regex
   `{word_char_only}` matches the default form used throughout MMAP. Custom
   forms such as `<<token>>` or `__SLOT__` are not auto-detected — pass them
   explicitly via `protected_placeholders`.
4. **JSON repair is format-level only.** It does not add missing fields,
   rename fields, or perform semantic repairs. See `json_repair_utility.md`
   for details.
5. **Report is advisory only.** Nothing in the codebase enforces the
   recommendation — it is up to the caller to inspect `report.ok` /
   `report.overall_status` / the nested `report.audit_report` and decide.

---

## Safety guardrails

1. **No LLM call.** Zero dependency on `mmap_optimizer.model.*` or any LLM.
2. **No optimizer loop change.** Nothing calls this module automatically.
3. **No CLI integration.** No CLI flags reference this module.
4. **No scenario integration.** No scenario code reads or writes the report.
5. **No filesystem writes from inside the utility.** The caller decides
   where, if anywhere, to write JSON or rendered summaries.
6. **Frozen dataclass output.** Reports are immutable once built.
7. **Deterministic.** Same inputs always produce identical outputs — hashes,
   issues, and all fields.
8. **TypeError for non-str inputs.** Protects against accidental numeric or
   None input.
9. **apply_json_repair defaults to False.** Backward-compatible; must be
   explicitly enabled.
10. **No eval / ast.literal_eval.** JSON parsing uses `json.loads` only.

---

## Test coverage

Tests live in
[tests/test_prompt_rewrite_safety_report.py](file:///workspace/tests/test_prompt_rewrite_safety_report.py)
and cover 69 test cases across the following areas:

- Report construction (unchanged text, numbering defect + refactor on,
  numbering defect + refactor off, payload violation, placeholder removal,
  field rename, metadata round-trip, target_id preservation, hash stability)
- Audit item composition (3-4 expected item IDs, numbering count in evidence,
  payload count in evidence, hash chain in traceability evidence,
  fail→blocker severity, warning→minor severity)
- Serialization (to_dict stability, to_json output, from_dict round-trip,
  nested audit report round-trip, JSON-safe metadata, summary rendering,
  legacy dict handling)
- Guardrails (no forbidden imports, no CLI/scenario integration, no
  filesystem writes, input strings unchanged, TypeError on bad types,
  determinism across calls, no eval/literal_eval)
- Integration with underlying utilities (numbering output consistency,
  immutable payload validator consistency, audit item structure,
  apply_numbering_refactor default True, protected_placeholders forwarded,
  frozen dataclass assertion, report JSON round-trip)
- JSON repair integration (apply_json_repair default False, disabled
  behavior, success behavior, failure behavior, ordering, hash traceability,
  summary rendering)

Run:

```bash
python -m pytest tests/test_prompt_rewrite_safety_report.py -q
```