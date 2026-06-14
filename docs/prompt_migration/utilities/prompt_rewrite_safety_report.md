# Prompt Rewrite Safety Report Utility

**Module:** `mmap_optimizer.prompt.rewrite_safety`

**Purpose:** A deterministic wrapper that combines three previously-shipped
explicit utilities into a single structured *safety report* for prompt
rewrites. Given an `original` prompt text and a `rewritten` prompt text, it
produces a `PromptRewriteSafetyReport` containing:

- **numbering** analysis (via `mmap_optimizer.prompt.numbering_refactor`)
- **immutable-payload** analysis (via `mmap_optimizer.prompt.immutable_payload`)
- **audit-checklist** consolidation (via `mmap_optimizer.prompt.audit_checklist`)

This utility is the **explicit-call** companion to three existing pattern
utilities. It is never wired into the optimizer loop, CLI, or any scenario.

---

## Relation to Pattern Library

| Pattern | Companion utility |
|---|---|
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
  equals `rewritten`, and the utility still performs immutable-payload and
  audit analysis.

---

## API

| Symbol | Purpose |
|---|---|
| `build_prompt_rewrite_safety_report(*, target_id, original, rewritten, apply_numbering_refactor=True, protected_placeholders=None, metadata=None)` | Primary entry point. Returns a `PromptRewriteSafetyReport`. |
| `PromptRewriteSafetyReport` | Frozen dataclass with 12 fields (see below). |
| `prompt_rewrite_safety_report_to_json(report, *, indent=2, sort_keys=False)` | Serialize to JSON. |
| `prompt_rewrite_safety_report_from_dict(data)` | Reconstruct a report from a plain dict (inverse of `report.to_dict()`). |
| `render_prompt_rewrite_safety_summary(report)` | Plain-text human-readable summary. |

### PromptRewriteSafetyReport schema

```python
@dataclass(frozen=True)
class PromptRewriteSafetyReport:
    target_id: str                        # e.g. "prompt-v3-to-v4"
    ok: bool                               # True iff overall == pass + payload intact
    overall_status: str                    # "pass" | "warning" | "fail"
    original_hash: str                     # SHA-256 of original
    rewritten_hash: str                    # SHA-256 of rewritten
    normalized_rewritten_hash: str         # SHA-256 after numbering-refactor
    numbering_issue_count: int             # issues from detect_numbering_issues
    immutable_payload_issue_count: int     # issues from validate_immutable_payload
    audit_issue_count: int                 # items in audit_report with status != pass
    normalized_rewritten: str              # post-refactor rewrite text
    audit_report: AuditChecklistReport     # inner audit report (3 items)
    metadata: dict[str, Any]               # caller-supplied context
```

---

## Audit item semantics

The inner `audit_report` always contains exactly three audit items:

| id | dimension | when it flags |
|---|---|---|
| `payload_integrity` | `payload_integrity` | The payload validation fails; any placeholder renames, field renames, heading deletions, new rules, etc. |
| `format_validity` | `format_validity` | Numbering issues were detected in the rewritten text; warning if `apply_numbering_refactor=True` since refactor output is provided; warning if `False` and numbering defects remain; pass otherwise. |
| `rewrite_traceability` | `format_validity` | Reports hash chain: rewritten vs. normalized-rewritten. If they differ (numbering-refactor), flags as warning with both hashes in evidence. |

### `ok` vs. `overall_status`

- `ok` is True **only when** `overall_status != "fail"` **and** the
  immutable-payload check reported zero issues. This is a conservative gate:
  a numbering-only rewrite (payload-preserved) will produce `ok=True` but
  `overall_status="warning"`; callers can inspect `overall_status` for finer
  granularity.
- `overall_status` mirrors the status aggregation logic of the underlying
  audit-checklist report: `fail` wins over `warning`, which wins over `pass`.

---

## Examples

### Numbering defect, payload preserved

```text
Original:      ## Instructions\n1. Read {question}\n2. Emit {answer}\n
Rewritten:     ## Instructions\n1. Read {question}\n1. Emit {answer}\n
```

This produces:

- `numbering_issue_count > 0` (list numbering detected)
- `immutable_payload_issue_count == 0` (placeholders preserved)
- `ok = True`, `overall_status = "warning"`
- `rewritten_hash != normalized_rewritten_hash` (reflects the refactor)

### Payload violation

```text
Original:      "## Instructions\n1. Read {question}\n2. Emit {answer}\n"
Rewritten:     "## Instructions\n1. Read question\n2. Emit answer\n"
```

This produces:

- `immutable_payload_issue_count > 0`
- `ok = False`, `overall_status = "fail"`
- The `payload_integrity` audit item is marked `severity="blocker"` with the
  missing placeholder details in its `issue` field.

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
4. **Report is advisory only.** Nothing in the codebase enforces the
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

---

## Test coverage

Tests live in
[tests/test_prompt_rewrite_safety_report.py](file:///workspace/tests/test_prompt_rewrite_safety_report.py)
and cover 40+ test cases across the following areas:

- Report construction (unchanged text, numbering defect + refactor on,
  numbering defect + refactor off, payload violation, placeholder removal,
  field rename, metadata round-trip, target_id preservation, hash stability)
- Audit item composition (3 expected item IDs, numbering count in evidence,
  payload count in evidence, hash chain in traceability evidence,
  fail→blocker severity, warning→minor severity)
- Serialization (to_dict stability, to_json output, from_dict round-trip,
  nested audit report round-trip, JSON-safe metadata, summary rendering)
- Guardrails (no forbidden imports, no CLI/scenario integration, no
  filesystem writes, input strings unchanged, TypeError on bad types,
  determinism across calls)
- Integration with underlying utilities (numbering output consistency,
  immutable payload validator consistency, audit item structure,
  apply_numbering_refactor default True, protected_placeholders forwarded,
  frozen dataclass assertion, report JSON round-trip)

Run:

```bash
python -m pytest tests/test_prompt_rewrite_safety_report.py -q
```
