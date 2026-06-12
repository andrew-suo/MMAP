# MMAP Optimizer MVP

This repository contains an MVP skeleton for a multimodal prompt optimization framework. It implements the foundations discussed in the design phase:

- Prompt IR with frozen external output-schema contracts.
- Prompt rendering with section markers.
- JSON/JSONL file-based logging for reproducible optimization rounds.
- Extraction evaluation with parse, schema, and primary-answer checks.
- Dynamic validation sampling instead of a fixed validation set.
- Patch, compression, and few-shot data models for later optimization phases.
- A smoke CLI that runs one no-patch round using mock outputs stored in sample metadata.

## Quick smoke run

```bash
python -m mmap_optimizer.cli.main run-smoke \
  --data-dir data \
  --run-dir runs/smoke \
  --batch-size 2 \
  --dynamic-validation-batch-size 1
```

The smoke command loads samples, prompts, and schemas; renders prompt IRs; runs mock extraction; evaluates outputs; writes round logs; and prints basic metrics.

## MVP module map

- `mmap_optimizer/prompt`: Prompt IR, immutable schema contracts, rendering, initialization.
- `mmap_optimizer/evaluation`: schema validation and primary-answer evaluation.
- `mmap_optimizer/sampling`: optimization and dynamic-validation samplers.
- `mmap_optimizer/orchestration`: MVP round runner and run records.
- `mmap_optimizer/patch`: patch schema, validation, merge, and application foundations.
- `mmap_optimizer/testing`: strict fixed/broken transition summaries.
- `mmap_optimizer/fewshot`: few-shot candidate/example/set schemas.
- `mmap_optimizer/compression`: compression report schema.
- `mmap_optimizer/storage`: JSON/JSONL persistence.

## Current scope

This is the first implementation slice. It intentionally focuses on stable data models, logging, prompt rendering, evaluation, dynamic validation, and a runnable round skeleton. Full LLM patch generation, analysis shadow evolution, compression execution, and few-shot search are represented by interfaces/data models and are intended as next implementation steps.
