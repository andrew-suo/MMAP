# MMAP Optimizer MVP

This repository contains an MVP skeleton for a multimodal prompt optimization framework. It implements the foundations discussed in the design phase:

- Prompt IR with frozen external output-schema contracts.
- Prompt rendering with section markers.
- JSON/JSONL file-based logging for reproducible optimization rounds.
- Extraction evaluation with parse, schema, and primary-answer checks.
- Dynamic validation sampling instead of a fixed validation set.
- A minimal text-patch loop: analysis-output parsing, patch validation, strict individual patch tests, and PromptVersion updates.
- Compression and few-shot data models for later optimization phases.
- A smoke CLI that runs one round using mock outputs stored in sample metadata.

## Quick smoke run

```bash
python -m mmap_optimizer.cli.main run-smoke \
  --data-dir data \
  --run-dir runs/smoke \
  --batch-size 2 \
  --dynamic-validation-batch-size 1
```

The smoke command loads samples, prompts, and schemas; renders prompt IRs; runs mock extraction; evaluates outputs; optionally consumes mock analysis patch outputs; writes round logs; and prints basic metrics.

## MVP module map

- `mmap_optimizer/prompt`: Prompt IR, immutable schema contracts, rendering, initialization.
- `mmap_optimizer/evaluation`: schema validation and primary-answer evaluation.
- `mmap_optimizer/sampling`: optimization and dynamic-validation samplers.
- `mmap_optimizer/orchestration`: MVP round runner and run records.
- `mmap_optimizer/patch`: patch schema, validation, merge, application, and strict update foundations.
- `mmap_optimizer/testing`: strict fixed/broken transition summaries.
- `mmap_optimizer/fewshot`: few-shot candidate/example/set schemas.
- `mmap_optimizer/compression`: compression report schema.
- `mmap_optimizer/storage`: JSON/JSONL persistence.

## Current scope

This implementation slice focuses on stable data models, logging, prompt rendering, evaluation, dynamic validation, and a runnable text-patch round skeleton. Analysis outputs can now be parsed into patch candidates, each candidate is applied to a temporary PromptVersion for model-backed testing, and accepted patches can update the active extraction PromptVersion after strict tests. Full production LLM prompt engineering for patch generation, analysis shadow evolution, compression execution, and few-shot search remain next implementation steps.


## Mock prompt-dependent outputs

Tests and smoke data can keep model calls deterministic while still exercising temporary PromptVersion rendering. A sample may provide `metadata.mock_prompt_outputs` rules; `MockModelClient` returns the first rule whose `contains` text appears in the rendered system prompt, otherwise it falls back to `metadata.mock_output`. This allows patch tests to validate the real apply-render-run-evaluate path without external API calls.


## Bundle safety

Each individually accepted patch is now re-tested as part of an accepted-patch bundle before it can update the active extraction prompt. If the full bundle is toxic, the round runner performs greedy safe-subset selection: patches are tried in descending fixed-sample count order, and any patch that introduces bundle-level toxicity is rejected with a bundle rejection reason.
