# Prompt Utility Report Artifact Schema

**Module:** `mmap_optimizer.prompt.utility_report_artifact`

**Purpose:** Define a stable, JSON-serializable artifact contract that wraps a
`PromptUtilityRunResult` into a content-addressable, auditable record. The
artifact can be written to disk, logged, or forwarded to downstream tooling —
but **nothing in this module writes files**. Callers that want persistence are
responsible for the actual write.

---

## Relation to the Prompt Utility Runner

The prompt utility runner (`mmap_optimizer.prompt.utility_runner`) produces a
`PromptUtilityRunResult` — an in-memory dataclass with `reports`, `issues`,
`ok`, and other fields. This artifact module wraps that result into a
self-contained, hash-addressable JSON-compatible structure:

```python
from mmap_optimizer.prompt.utility_report_artifact import (
    build_prompt_utility_report_artifact,
)
artifact = build_prompt_utility_report_artifact(
    result=run_result,
    original=original_text,
    rewritten=rewritten_text,
)
```

---

## Artifact Schema

```json
{
  "artifact_type": "prompt_utility_report",
  "artifact_version": "1.0",
  "target_id": "invoice_prompt_v3",
  "created_at": "2026-06-14T00:00:00Z",
  "ok": false,
  "enabled": true,
  "report_only": true,
  "utilities": ["json_repair", "structured_schema"],
  "issues": ["structured_schema: ok=False; 1 issue(s)"],
  "reports": { ... },
  "hashes": {
    "original_hash": "sha256_hex",
    "rewritten_hash": "sha256_hex",
    "reports_hash": "sha256_hex",
    "artifact_hash": "sha256_hex"
  },
  "metadata": {}
}
```

### Field Definitions

| Field | Type | Description |
|---|---|---|
| `artifact_type` | `str` | Always `"prompt_utility_report"` |
| `artifact_version` | `str` | Always `"1.0"` |
| `target_id` | `str` | Identifier from the runner call |
| `created_at` | `str` | ISO-8601 UTC timestamp; caller-supplied or auto-generated |
| `ok` | `bool` | Mirrors `result.ok` |
| `enabled` | `bool` | Mirrors `result.enabled` |
| `report_only` | `bool` | Mirrors `result.report_only` |
| `utilities` | `list[str]` | Utilities that were executed |
| `issues` | `list[str]` | Human-readable issue strings |
| `reports` | `dict` | Nested per-utility report dicts |
| `hashes` | `dict` | Content-addressable hashes (see below) |
| `metadata` | `dict` | Merged metadata (result metadata + caller-supplied) |

---

## Hashing Semantics

All hashes are SHA-256 digests of the canonical JSON representation of their
source data, ensuring cross-process determinism:

| Hash | Source | Canonical form |
|---|---|---|
| `original_hash` | Raw original string | `canonical_json(original)` |
| `rewritten_hash` | Raw rewritten string | `canonical_json(rewritten)` |
| `reports_hash` | Canonical reports dict | `canonical_json(reports)` |
| `artifact_hash` | Artifact body excluding `artifact_hash` | Recursive canonical JSON |

**`artifact_hash` self-reference exclusion:** when computing `artifact_hash`,
the `artifact_hash` key itself is removed from the body before hashing. This
prevents a circular dependency where the hash would change every time it is
computed.

---

## `created_at` Behavior

- If `created_at` is supplied to `build_prompt_utility_report_artifact(...)`, it
  is used verbatim (caller controls the timestamp).
- If omitted, the function generates a UTC ISO string:
  `YYYY-MM-DDTHH:MM:SSZ`
- Tests should inject a fixed `created_at` value to ensure deterministic
  assertions.

---

## Metadata Merge

`artifact.metadata` is the result of merging `result.metadata` with the
caller-supplied `metadata` argument. Caller-supplied keys take precedence in
the case of overlap.

```python
result.metadata == {"scenario": "example", "runner": "v1"}
build(..., metadata={"scenario": "override", "extra": "field"})
# artifact.metadata == {"scenario": "override", "runner": "v1", "extra": "field"}
```

---

## Validation Behavior

`validate_prompt_utility_report_artifact(artifact)` returns a `tuple[str, ...]`
of issues. An empty tuple means the artifact is well-formed.

Validation checks:

- `artifact_type == "prompt_utility_report"`
- `artifact_version == "1.0"`
- `target_id` non-empty string
- `created_at` non-empty string
- `ok`, `enabled`, `report_only` are `bool`
- `utilities` and `issues` are sequences of `str`
- `reports` and `metadata` are dict-like
- `hashes` has all four required SHA-256 hex strings
- `reports_hash` matches recomputed `stable_hash(reports)`
- `artifact_hash` matches recomputed artifact body hash

Validation **does not throw** on wrong input types — it returns a single-item
tuple describing the problem.

---

## Explicit Invocation Only

Nothing in `mmap_optimizer` imports this module automatically. It must be
imported and called by a human caller or CI pipeline.

---

## No-Write Guarantee

This module never opens a file for writing, never calls `Path.write_text`,
and never delegates write operations. Callers that want to persist the JSON
artifact must do so outside this module:

```python
import json
from pathlib import Path
artifact_json = prompt_utility_report_artifact_to_json(artifact)
Path("audit/report.json").write_text(artifact_json)  # caller writes
```

---

## API Reference

```python
# Constants
ARTIFACT_TYPE      # "prompt_utility_report"
ARTIFACT_VERSION   # "1.0"

# Dataclasses
class PromptUtilityReportHashes:
    original_hash: str
    rewritten_hash: str
    reports_hash: str
    artifact_hash: str
    def to_dict(self) -> dict[str, str]: ...

class PromptUtilityReportArtifact:
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
    def to_dict(self) -> dict[str, Any]: ...

# Builders / Serializers
def build_prompt_utility_report_artifact(
    *,
    result: PromptUtilityRunResult,
    original: str,
    rewritten: str,
    created_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PromptUtilityReportArtifact: ...

def prompt_utility_report_artifact_to_json(
    artifact: PromptUtilityReportArtifact,
) -> str: ...  # pretty-printed JSON

def prompt_utility_report_artifact_from_dict(
    data: Mapping[str, Any],
) -> PromptUtilityReportArtifact: ...  # round-trip; raises ValueError

def validate_prompt_utility_report_artifact(
    artifact: PromptUtilityReportArtifact | Mapping[str, Any],
) -> tuple[str, ...]: ...  # empty = valid

# Internal helpers (public for testability)
def stable_hash(value: Any) -> str: ...
def canonicalize_for_report(value: Any) -> Any: ...
```

---

## Example

```python
from mmap_optimizer.prompt.utility_runner import run_prompt_utilities, PromptUtilityRunConfig
from mmap_optimizer.prompt.utility_report_artifact import (
    build_prompt_utility_report_artifact,
    prompt_utility_report_artifact_to_json,
    validate_prompt_utility_report_artifact,
)

result = run_prompt_utilities(
    target_id="invoice-v3",
    original=original_text,
    rewritten=rewritten_text,
    config=PromptUtilityRunConfig(
        enabled=True,
        utilities=("structured_schema",),
        structured_schema={"type": "object", "required": ["invoice_id"]},
    ),
)
artifact = build_prompt_utility_report_artifact(
    result=result,
    original=original_text,
    rewritten=rewritten_text,
)
issues = validate_prompt_utility_report_artifact(artifact)
if issues:
    print("Artifact invalid:", issues)
else:
    print("Artifact valid.")
    print(prompt_utility_report_artifact_to_json(artifact))
```

---

## Limitations

- No file I/O in this module. Persistence is the caller's responsibility.
- No LLM calls.
- No JSON repair (the artifact wraps whatever the runner produced).
- No external dependencies beyond the Python standard library.
- `artifact_hash` is not a content-integrity seal for the entire pipeline — it
  only covers the fields present in the artifact itself.
