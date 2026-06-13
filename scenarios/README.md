# MMAP Scenarios

This directory contains scenario definitions for the MMAP optimizer.

## Scenario Convention

A valid scenario must have the following structure:

```
scenarios/
  README.md                          # This file
  <scenario_id>/
    scenario.yaml                    # Scenario manifest
    optimizer.yaml                   # Optimizer configuration
    README.md                        # Scenario documentation
    data/                            # Data directory
    prompts/                         # Prompts directory
    schemas/                         # Schemas directory
```

## Standard Files
- `scenario.yaml` - Scenario manifest with metadata
- `optimizer.yaml` - Optimizer configuration
- `README.md` - Scenario documentation

## Standard Directories
- `data/` - Contains sample and ground truth data
- `prompts/` - Contains prompt templates
- `schemas/` - Contains output schemas

## Using Scenarios

List scenarios:
```bash
python -m mmap_optimizer.cli.main scenario list --scenarios-dir scenarios
```

Validate a scenario:
```bash
python -m mmap_optimizer.cli.main scenario validate default --scenarios-dir scenarios
```

Show scenario info:
```bash
python -m mmap_optimizer.cli.main scenario info default --scenarios-dir scenarios
```

Run with a scenario:
```bash
python -m mmap_optimizer.cli.main run --scenario scenarios/default
```
