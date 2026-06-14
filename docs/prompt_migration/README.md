# Prompt Migration Guide

This directory contains the prompt migration and absorption plan for the MMAP project.

## Overview

This plan addresses how to absorb capabilities from old project prompts into the current MMAP system. The approach focuses on **capability modules** (patterns) rather than direct text reuse, ensuring safe and reversible integration.

## Documents

1. **[Current Prompt Inventory](current_prompt_inventory.md)** - Complete catalog of current prompt assets
2. **[Prompt Absorption Strategy](prompt_absorption_strategy.md)** - How to absorb old prompt capabilities
3. **[Migration Plan](migration_plan.md)** - Phased approach to prompt enhancement

## Quick Summary

### Current State
The MMAP project has a solid prompt infrastructure with:
- 2 main raw prompts (extraction, analysis)
- 14 optimizer templates
- Comprehensive prompt health and self-check systems
- Evaluation and optimization capabilities
- 8 test files covering prompt functionality

### Key Findings
1. **Strengths**: Clear structure, frozen output schemas, health checks
2. **Weaknesses**: Limited examples, basic self-check, no systematic negative examples
3. **Opportunities**: Pattern library, enhanced evaluation, better few-shot

### Migration Strategy
1. Extract patterns, not text
2. Use capability modules, not direct mapping
3. Phase 1-2: Inventory and pattern library (no behavior change)
4. Phase 3: One prompt upgrade (evaluation prompt recommended)
5. Phase 4: Scenario-gated rollout
6. Phase 5: Default adoption (after validation)

## User Actions Required

To proceed with the migration:

1. **Place old prompts** in `source_prompts/` directory
2. **Review mapping table** in `prompt_absorption_strategy.md`
3. **Prioritize patterns** for Phase 2 implementation

## Testing

All phases maintain existing test coverage:
```bash
python -m pytest -q
python -m mmap_optimizer.cli.main --help
python -m mmap_optimizer.cli.main run-smoke --rounds 1 --run-dir /tmp/mmap-smoke
python -m mmap_optimizer.cli.main run-smoke --rounds 1 --run-dir /tmp/mmap-smoke --resume
```

## Key Constraints

- No direct prompt replacement
- No default behavior changes until Phase 5
- All changes must pass existing tests
- Pattern-based absorption only
- Testable enhancements only

## Directory Structure

```
docs/prompt_migration/
├── README.md                    # This file
├── current_prompt_inventory.md  # Current asset catalog
├── prompt_absorption_strategy.md # Absorption methodology
├── migration_plan.md            # Phased implementation plan
└── source_prompts/              # User: place old prompts here
    ├── extraction/
    │   ├── system_prompts/
    │   ├── task_prompts/
    │   └── evaluation_prompts/
    └── analysis/
        ├── patch_generation/
        └── evaluation/
```
