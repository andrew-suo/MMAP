# MMAP Optimizer

Multimodal prompt optimization framework that iteratively improves extraction and analysis prompts through automated patch generation, validation, compression, and few-shot optimization.

## Features

- **Prompt IR & Versioning** — Structured `PromptIR` with section-level control, immutable output-schema contracts, and `PromptVersion` with full round/run-level provenance tracking
- **Patch Workflow** — Analysis-driven patch generation, self-describing constraints (`allowed_operation_types` / `forbidden_keywords` / `must_mention_section_ids`), tree-reduce merge, strict individual + bundle testing, and safe application with traceability
- **Round Stage State Machine** — Explicit `RoundStage` enum (15 stages from `INIT` to `COMPLETED`) for deterministic round progression tracking
- **Compression** — Line-budget and token-budget dual-threshold compression with behavior-preservation gates for both extraction and analysis prompts
- **Few-Shot Optimization** — Greedy slot optimization with persistent candidate pool, schema-complete example generation, and accuracy-delta promotion gates
- **Checkpoint & Snapshot** — `OptimizerCheckpoint` for run-state persistence and `PromptSnapshot` with rollback support for safe prompt mutation
- **Dynamic Validation** — Non-fixed validation set with label/difficulty coverage and recent-selection penalty
- **Config Safety** — Safe type conversion (`_int_safe` / `_float_safe`), instance-level `validate()` with range checks, and graceful fallback for invalid inputs
- **Debug Event Logger** — In-memory event counting, aggregation by stage/round, and JSONL persistence with cleanup controls
- **Multimodal Support** — OpenAI-compatible adapter for local/remote image assets as multimodal message parts

## Quick Start

```bash
# Smoke run with mock model
python -m mmap_optimizer.cli.main run-smoke \
  --data-dir data \
  --run-dir runs/smoke \
  --batch-size 2 \
  --dynamic-validation-batch-size 1 \
  --rounds 2 \
  --extraction-line-budget 120 \
  --fewshot-enabled

# Configurable run with real model
python -m mmap_optimizer.cli.main run --config configs/optimizer.yaml

# Prompt health check without starting a run
python -m mmap_optimizer.cli.main check-prompt --data-dir data

# Resume an interrupted run
python -m mmap_optimizer.cli.main run-smoke --rounds 1 --run-dir /tmp/mmap-smoke --resume
```

## Architecture

```
mmap_optimizer/
├── prompt/           # Prompt IR, versioning, rendering, snapshots, health, contracts
│   ├── ir.py         # PromptSection + PromptIR (structured prompt representation)
│   ├── version.py    # PromptVersion with from_dict() + round/run provenance
│   ├── renderer.py   # PromptRenderer (IR → rendered text with section markers)
│   ├── snapshot.py   # save_prompt_snapshot() + rollback_to_snapshot()
│   ├── contract.py   # OutputSchemaContract (frozen external schema)
│   ├── health.py     # Prompt health validation
│   └── ...
├── patch/            # Patch schema, validation, merge, application
│   ├── schema.py     # Patch (with constraints, to_dict, compact_dict)
│   ├── validator.py  # PatchValidator (constraint-aware, detailed error reasons)
│   ├── applier.py    # PatchApplier (round_id/run_id traceability)
│   ├── tree_reduce.py # Tree-reduce merge with conflict detection
│   └── ...
├── orchestration/    # Round runner, optimizer loop, records, checkpoint
│   ├── records.py    # RoundStage enum + OptimizationRound + RunRecord
│   ├── round_runner.py # Single-round execution with stage tracking
│   ├── optimizer_loop.py # Serial multi-round loop
│   ├── checkpoint.py # OptimizerCheckpoint (save/restore active prompts)
│   └── ...
├── compression/      # Line/token budget compression
│   ├── engine.py     # CompressionEngine (line_budget + token_budget)
│   ├── report.py     # CompressionReport (with token counts)
│   └── ...
├── evaluation/       # Extraction evaluation, schema validation, voting
├── sampling/         # Optimization + dynamic-validation samplers
├── fewshot/          # Few-shot candidate pool, slot optimization
├── analysis/         # Analysis output parsing, repair, evolution
├── core/             # Config, enums, hashing, scenario loading
│   ├── config.py     # OptimizerConfig with validate() + safe converters
│   ├── enums.py      # PromptType, PatchStatus, RunType, EvaluationStatus
│   └── ...
├── debug/            # Debug event logger with aggregation
│   └── logger.py     # DebugEventLogger (counts, summary, clear, reset)
├── model/            # Mock + OpenAI-compatible multimodal client
├── storage/          # JSON/JSONL persistence
├── templates/        # Versioned prompt template registry
├── testing/          # Patch test runner, suite builder, transitions
├── metrics/          # Round metrics, section contribution, trend
├── dataset/          # Sample loader and schema
└── cli/              # Command-line interface
```

## Core Concepts

### Prompt Version Provenance

Every `PromptVersion` carries `created_by_round_id` and `created_by_run_id`, enabling full traceability from any prompt back to the optimization step that produced it. `PromptVersion.from_dict()` reconstructs versions from serialized data while preserving unknown fields in `_extra` to prevent data loss across version upgrades.

### Patch Self-Describing Constraints

Patches carry their own `constraints` dict with three validation dimensions:
- `allowed_operation_types` — restrict which operations this patch may use
- `forbidden_keywords` — reject patches that mention protected terms (e.g., schema mutation)
- `must_mention_section_ids` — require patch text to reference specific sections

`PatchValidator` checks these constraints before any patch is applied, with detailed error reasons for debugging.

### Round Stage State Machine

Each `OptimizationRound` tracks its current stage via the `RoundStage` enum:

```
INIT → OPTIMIZATION_BATCH_SELECT → BASELINE_EVAL → DYNAMIC_VALIDATION
     → PATCH_GENERATION → PATCH_VALIDATION → PATCH_TREE_REDUCE
     → PATCH_EVAL → PATCH_RANKING → PATCH_APPLY → COMPRESSION
     → FEWSHOT → ANALYSIS_EVOLUTION → METRICS → COMPLETED
                                                     ↘ FAILED
```

### Dual-Budget Compression

`CompressionEngine` supports both line-budget and token-budget thresholds. When either budget is exceeded, the engine ranks mutable sections, removes blank/duplicate lines one section at a time, and runs a behavior-preservation gate before promotion. `CompressionReport` records `token_count_before`, `token_count_after`, `token_budget`, and `token_reduction`.

### Config Safety

`OptimizerConfig.validate()` performs instance-level range checks on all numeric fields. `_int_safe()` and `_float_safe()` handle `None`, non-numeric strings, and nested types gracefully, falling back to defaults instead of raising exceptions. `optimizer_config_from_mapping()` uses these safe converters throughout.

## Configuration

```yaml
# configs/optimizer.yaml
models:
  extraction:
    provider: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-4o
    api_key_env: OPENAI_API_KEY
  optimizer:
    provider: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-4o
    api_key_env: OPENAI_API_KEY

optimizer:
  batch_size: 5
  max_text_rounds: 5
  extraction_line_budget: 120
  analysis_line_budget: 80
  extraction_token_budget: 4000
  analysis_token_budget: 2000
  fewshot_enabled: true

dynamic_validation:
  min_label_count: 1
  cover_difficulty_bins: true
  recent_window_rounds: 3
  max_recent_selections: 2

execution:
  max_workers: 4
  timeout_seconds: 120
```

## Testing

```bash
# Run all tests
python -m pytest -q

# Run P0-P2 feature coverage tests
python -m pytest tests/test_p0_p2_feature_coverage.py -v

# Smoke test
python -m mmap_optimizer.cli.main run-smoke --rounds 1 --run-dir /tmp/mmap-smoke
```

## Prompt Migration

The `docs/prompt_migration/` directory contains the migration and absorption plan for integrating capabilities from legacy prompts into the current system. The approach focuses on **capability modules** (patterns) rather than direct text reuse, ensuring safe and reversible integration. See [docs/prompt_migration/README.md](docs/prompt_migration/README.md) for details.

## Key Design Decisions

- **Frozen output schemas** — External output-schema contracts are immutable; patches that modify schema sections are rejected
- **Behavior-preservation gates** — Compression and few-shot changes must preserve baseline extraction predictions and evaluation statuses
- **No early stopping** — The optimizer loop does not early-stop when a text round accepts no patches, because analysis evolution, compression, and few-shot phases still need deterministic round accounting
- **Dynamic validation** — Validation sets are intentionally not fixed across rounds; composition is driven by label/difficulty coverage with a recent-selection penalty
- **Parallel IR models** — Runtime optimizer prompts (`mmap_optimizer.prompt.ir.PromptIR`) and evaluation-prompt optimization prompts (`mmap_optimizer.prompts.PromptIR`) are semantically distinct and intentionally separate
