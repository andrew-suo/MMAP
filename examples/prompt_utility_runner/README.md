# Non-default prompt utility runner example

## Purpose

Demonstrates how to use the scenario-gated prompt utility runner
(`mmap_optimizer.prompt.utility_runner`) in a manual, non-default workflow.

This example is **NOT** wired into the optimizer loop, the CLI, or any
default scenario. It is a standalone script that must be run by hand.

## Why this is non-default

Nothing in the codebase imports or calls this example automatically:

- No prompt in `prompts/` references this script.
- No default CLI command (e.g. `mmap_optimizer.cli.main`) reads it.
- No scenario default behavior runs it.
- No optimizer loop imports it.
- It must be explicitly invoked by a human.

## How to run

From the repository root:

```bash
python -m examples.prompt_utility_runner.run_prompt_utility_example
```

(You may need to install the local package first:
`pip install -e .` or add the project root to `PYTHONPATH`.)

## What it demonstrates

The script:

1. Reads two local sample prompt files:
   - `sample_original_prompt.md` — the "original" prompt.
   - `sample_rewritten_prompt.md` — a candidate rewrite with deliberate
     but minor formatting differences so JSON repair and numbering refactor
     are exercised.
2. Builds a `PromptUtilityRunConfig` with `enabled=True`.
3. Calls `run_prompt_utilities(...)` on the two sample texts.
4. Prints a human-readable summary.
5. Prints a JSON-serializable report.
6. Exits with return code 0.
7. Writes **nothing** to disk.
8. Does **not** call an LLM or read any optimizer config.

## Report-only guarantee

- The sample prompt files are never modified.
- The runner never applies changes to any prompt.
- The normalized / repaired text produced by sub-utilities is only shown
  in the JSON report.

## Supported utilities in this example

- `json_repair` — detects JSON structure issues in the rewritten prompt.
- `numbering_refactor` — detects numbering issues in the rewritten prompt.
- `immutable_payload` — validates that placeholders / structural content
  are preserved between original and rewritten.
- `rewrite_safety` — the composed report that combines all the above and
  adds an audit checklist.

Each utility's output is placed in the `reports[utility_name]` field of the
result object.

## Sample output structure

```
PROMPT UTILITY RUNNER — SUMMARY
...
  ok          : True/False
  utilities   : json_repair, numbering_refactor, immutable_payload, rewrite_safety
  reports:
    json_repair: (dict with N key(s))
    numbering_refactor: (dict with N key(s))
    immutable_payload: (dict with N key(s))
    rewrite_safety: (dict with N key(s))
...

PROMPT UTILITY RUNNER — JSON REPORT
{
  "target_id": "...",
  "enabled": true,
  "report_only": true,
  "utilities": ["json_repair", "..."],
  "ok": true/false,
  "reports": {
    "json_repair": { ... },
    "numbering_refactor": { ... },
    "immutable_payload": { ... },
    "rewrite_safety": { ... }
  },
  "issues": [ ... ],
  "metadata": { ... }
}
```

## Safety guardrails

- No LLM call. Zero dependency on `mmap_optimizer.model.*`.
- No filesystem writes. All output is on stdout.
- Explicit invocation only — `python -m examples.prompt_utility_runner.run_prompt_utility_example`.
- Report-only — no prompt changes applied.
- Deterministic — same inputs always produce the same output.
- No `eval` / `ast.literal_eval`.
- No optimizer-loop, CLI, or scenario wiring.

## Limitations

1. The sample prompts are intentionally small and synthetic.
2. `json_repair` only reports on what it can fix. Markdown with embedded
   JSON may still trigger a numbering / immutable-payload difference even
   if JSON repair succeeds.
3. This example is for education — it is not a regression test. See
   `tests/test_prompt_utility_runner_example.py` for the regression test
   that exercises this example.
