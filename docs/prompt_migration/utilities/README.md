# Prompt-Migration Utilities (explicit-call only)

This directory documents the **explicit-call** utility modules in the
`mmap_optimizer.prompt.*` package. Each utility is a deterministic,
LLM-free, read-only text-analysis tool that must be explicitly imported
and invoked by a caller.

**None of these utilities are wired into the optimizer loop, CLI, or
scenario pipeline. They are tools for humans / CI pipelines.**

---

## Utilities

| Utility | Module | Purpose |
|---|---|---|
| **numbering-only-refactor** | `mmap_optimizer.prompt.numbering_refactor` | Repair Markdown heading / list / step numbering (`## 1. / ## 2.`, `1. / 2.`, `Step 1 / Step 2`) |
| **json-repair-position-valid** | `mmap_optimizer.prompt.json_repair` | Return a position-valid JSON body: strip fences, drop surrounding prose, remove trailing commas |
| **immutable-payload** | `mmap_optimizer.prompt.immutable_payload` | Validate that a rewrite preserves `{placeholders}`, field names, heading text, and rule text |
| **audit-checklist** | `mmap_optimizer.prompt.audit_checklist` | Build structured `AuditChecklistReport` with pass/warning/fail semantics and blocker/major/minor severity |
| **prompt-rewrite-safety-report** | `mmap_optimizer.prompt.rewrite_safety` | **Wrapper** that composes the above four into a single `PromptRewriteSafetyReport`; optionally includes JSON repair stage (`apply_json_repair=False` by default) |
| **scenario-gated-utility-runner** | `mmap_optimizer.prompt.utility_runner` | Explicit report-only orchestrator for prompt utilities; `enabled=False` by default; runs one or more utilities and returns a combined `PromptUtilityRunResult`; can optionally invoke structured-output-schema-checker. |
| **structured-output-schema-checker** | `mmap_optimizer.prompt.structured_output_schema` | Explicit report-only schema contract checker for JSON-like outputs; validation only, no repair, no LLM. |
| **prompt-utility-report-artifact** | `mmap_optimizer.prompt.utility_report_artifact` | Stable JSON-serializable artifact contract for `PromptUtilityRunResult`; content-addressable hashes; explicit invocation only; no writes |

---

## When to reach for which

| Your problem | Utility |
|---|---|
| "My human-generated rewrite has duplicate heading numbers" | `numbering_refactor` |
| "The model output is wrapped in Markdown fences or has trailing prose" | `json_repair` |
| "Did this proposed rewrite accidentally drop a placeholder?" | `immutable_payload` |
| "I need a structured audit trail for a review meeting / CI" | `audit_checklist` |
| "I want one report combining the four" | `rewrite_safety` (composes them; `apply_json_repair=False` by default) |
| "I want to run multiple utilities in one call and get a combined report" | `utility_runner` (explicit, `enabled=False` by default) |

---

## Safety contract

Every utility in this directory must satisfy:

- **No LLM call.** Zero dependency on `mmap_optimizer.model.*`.
- **No automatic invocation.** Nothing in `mmap_optimizer.optimizer.*`,
  `mmap_optimizer.cli.*`, or `mmap_optimizer.scenario.*` imports it.
- **No filesystem writes.** The utility never writes to disk; writing the
  report is the caller's choice.
- **Deterministic output.** Same inputs produce identical outputs.
- **`TypeError` for non-str inputs.** Protects against sloppy callers
  accidentally passing int/None/data objects.

If a future utility violates any of these, it must be fixed *before*
shipped — not after.

---

## Example workflow

A non-default, manual, report-only example is available at:

    examples/prompt_utility_runner/

It demonstrates how to explicitly invoke the prompt utility runner on
two sample prompt files. The example:

- Is **non-default**: must be run by hand.
- Is **manual-only**: `python -m examples.prompt_utility_runner.run_prompt_utility_example`
  or `python examples/prompt_utility_runner/run_prompt_utility_example.py`.
- Is **report-only**: writes nothing, applies no rewrite.
- Is **safe**: does not call an LLM, optimizer loop, CLI, or scenario runner.

See [examples/prompt_utility_runner/README.md](file:///workspace/examples/prompt_utility_runner/README.md)
for details.
