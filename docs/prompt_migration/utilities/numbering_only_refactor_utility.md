# Numbering-Only Prompt Refactor Utility

Location: `mmap_optimizer.prompt.numbering_refactor`

## Purpose

This module exposes a small, deterministic, text-level utility that
renumbers three kinds of markers inside a prompt body:

1. **Markdown heading numbers** — `## 1. Task`, `## 1. Rules` ...
2. **Ordered-list markers** — `1. foo`, `1. bar` ...
3. **Step numbers** — `Step 1: Load data`, `Step 1: Validate data` ...

The utility is intentionally narrow. It never calls a language model,
never rewrites sentences, and never changes content — it only adjusts
the leading numeric tokens on the lines above.

## Relation to the Pattern Library

This utility is the reference implementation of the **numbering-only
refactor** pattern documented in
`docs/prompt_migration/pattern_library/numbering_refactor_pattern.md`.
That pattern was extracted from the legacy prompt bundle
(`PROMPT_REFACTOR_PROMPT`, `PROMPT_REFACTOR_EVAL_PROMPT`) and the
adjoining JSON-repair / immutable-payload / incremental-fusion patterns.

## Default enabled: false

Nothing in the optimizer loop, CLI, or scenario pipeline imports this
module automatically. It must be invoked *explicitly* by a caller that
knows it wants a prompt's numbering rewritten, and the caller is
responsible for deciding where the rewritten text flows.

## Quick start

```python
from mmap_optimizer.prompt.numbering_refactor import (
    refactor_prompt_numbering_only,
    detect_numbering_issues,
)

raw = (
    "## 1. Task\n"
    "## 1. Rules\n"
    "1. foo\n"
    "1. bar\n"
    "Step 1: Load\n"
    "Step 1: Validate\n"
)

clean = refactor_prompt_numbering_only(raw)
# → "## 1. Task\n## 2. Rules\n1. foo\n2. bar\nStep 1: Load\nStep 2: Validate\n"

issues = detect_numbering_issues(raw)
# → [NumberingIssue(line_number=2, original="1", expected="2", issue_type="heading_duplicate"),
#     NumberingIssue(line_number=4, original="1", expected="2", issue_type="ordered_list_duplicate"),
#     NumberingIssue(line_number=6, original="1", expected="2", issue_type="step_duplicate")]
```

## Transformations

### Heading numbering

- Only lines matching `#{1,6} \d+[.)] .+` are renumbered.
- Headings without a numeric marker are preserved verbatim.
- Counts restart per heading level (`#`, `##`, `###`, ...).

### Ordered-list numbering

- Only lines matching `\s*\d+[.)] .+` are renumbered.
- The indentation level is preserved; nested lists restart independently.
- Bullet lists (`-`, `*`, `+`) and plain prose are never touched.

### Step numbering

- Only lines whose first non-whitespace token is `Step` followed by a
  digit and a colon (`\s*[Ss]tep \d+:\s*.+`) are renumbered.
- The word `step` inside plain prose is ignored.

## What is *never* modified

- Content inside fenced code blocks (``` ``` ... ``` ``` and `~~~`
  variants).
- Content inside `=== ICL 示例开始 ===` / `=== ICL 示例结束 ===`
  markers.
- `{placeholder}` tokens — `{question}`, `{answer}`, `{label}`,
  `{prediction}`, `{reference}`, `{context}`, `{input}`, `{output}`,
  or any other `{...}` token.
- JSON numbers inside prose or code blocks.
- Decision rules, output schema descriptions, example text, or any
  sentence that does not start with the specific patterns above.

## Safety guardrails

- **Deterministic.** Same input always produces the same output.
- **Idempotent.** `refactor_prompt_numbering_only` applied to its own
  output is a no-op.
- **Byte-preserving where possible.** Line endings and the overall
  number of lines are preserved. Only the leading numeric token on
  matching lines is rewritten.
- **Protected regions are opaque.** The utility never reads into a
  fenced code block or ICL block while deciding whether to renumber.

## Limitations

- The utility does not understand natural-language numbered items that
  are not anchored at the start of a line (e.g. `... and (2) the
  following`). Those are intentionally ignored.
- It cannot decide whether a heading *should* exist — only whether its
  numbering is sequential. Callers should only pass prompts whose
  structure they already trust.
- It does not integrate with the optimizer loop, CLI, or scenario
  engine. Explicit integration must be authored separately and reviewed
  before any default behavior changes.

## Test coverage

See `tests/test_prompt_numbering_refactor_utility.py`. The test file
covers:

- Heading numbering (duplicates, gaps, level independence, non-numeric
  headings, title text preservation, level preservation, alternate
  suffix).
- Ordered-list numbering (duplicates, gaps, indentation preservation,
  bullet-list isolation, plain prose isolation, JSON isolation,
  alternate suffix).
- Step numbering (duplicates, gaps, body text preservation, non-step
  prose isolation).
- Protected regions (fenced Python, fenced JSON, ICL delimited blocks,
  placeholder tokens, arbitrary `{...}` placeholders).
- No-logic-alteration invariants (line count preservation, token
  preservation, no rule deletion, no rule insertion, idempotency).
- Detection API (duplicate detection, gap detection, contract fields,
  protection-aware reporting, clean-prompt reporting).
- Composition API (importability, multi-pass behavior, type guarding,
  empty string handling).
