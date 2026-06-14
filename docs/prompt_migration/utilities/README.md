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

---

## When to reach for which

| Your problem | Utility |
|---|---|
| "My human-generated rewrite has duplicate heading numbers" | `numbering_refactor` |
| "The model output is wrapped in Markdown fences or has trailing prose" | `json_repair` |
| "Did this proposed rewrite accidentally drop a placeholder?" | `immutable_payload` |
| "I need a structured audit trail for a review meeting / CI" | `audit_checklist` |
| "I want one report combining the four" | `rewrite_safety` (composes them; `apply_json_repair=False` by default) |

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
