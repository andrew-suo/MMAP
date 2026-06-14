"""Non-default example: prompt utility runner on sample prompts.

This script demonstrates a manual, explicit, report-only invocation of the
scenario-gated prompt utility runner. It is *not* wired into the optimizer
loop, the CLI, or any default scenario. Run by hand:

    python examples/prompt_utility_runner/run_prompt_utility_example.py
    # or
    python -m examples.prompt_utility_runner.run_prompt_utility_example

The script:

1. Reads two sample prompt files (local to this directory).
2. Builds a PromptUtilityRunConfig with enabled=True.
3. Calls run_prompt_utilities(...) — this is the ONLY entry point used.
4. Prints a human-readable summary and a JSON-serializable report.
5. Writes nothing. Calls no LLM. Reads no optimizer config.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Bootstrap: add the repo root to sys.path so the script works both as
#   python examples/prompt_utility_runner/run_prompt_utility_example.py
#   python -m examples.prompt_utility_runner.run_prompt_utility_example
# as well as when the package is already on PYTHONPATH (pip install -e .).
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mmap_optimizer.prompt.utility_runner import (
    PromptUtilityRunConfig,
    prompt_utility_run_result_to_json,
    render_prompt_utility_run_summary,
    run_prompt_utilities,
)


EXAMPLES_DIR = Path(__file__).resolve().parent
ORIGINAL_PATH = EXAMPLES_DIR / "sample_original_prompt.md"
REWRITTEN_PATH = EXAMPLES_DIR / "sample_rewritten_prompt.md"


def main() -> int:
    original = ORIGINAL_PATH.read_text(encoding="utf-8")
    rewritten = REWRITTEN_PATH.read_text(encoding="utf-8")

    config = PromptUtilityRunConfig(
        enabled=True,
        utilities=(
            "json_repair",
            "numbering_refactor",
            "immutable_payload",
            "rewrite_safety",
        ),
        apply_json_repair=True,
        apply_numbering_refactor=True,
        report_only=True,
        protected_placeholders=("invoice_id", "amount", "currency"),
        metadata={"example": "prompt_utility_runner_example"},
    )

    result = run_prompt_utilities(
        target_id="prompt_utility_runner_example",
        original=original,
        rewritten=rewritten,
        config=config,
    )

    # --- summary section ---
    print("=" * 60)
    print("PROMPT UTILITY RUNNER — SUMMARY")
    print("=" * 60)
    print(render_prompt_utility_run_summary(result))

    # --- JSON report section ---
    print()
    print("=" * 60)
    print("PROMPT UTILITY RUNNER — JSON REPORT")
    print("=" * 60)
    print(prompt_utility_run_result_to_json(result, indent=2, sort_keys=True))

    # --- end markers ---
    print()
    print("=" * 60)
    print("END OF REPORT — ok=%s; enabled=%s" % (result.ok, result.enabled))
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
