# Scenario directory convention

A scenario is a reproducible optimizer fixture under `scenarios/<scenario_id>/`.
Each scenario should contain:

- `scenario.yaml` with scenario metadata and path overrides.
- `optimizer.yaml` with scenario-specific optimizer config overrides.
- `data/` with `samples.jsonl`, `ground_truth.jsonl`, and optional assets.
- `prompts/` with `extraction.txt` and `analysis.txt` unless overridden.
- `schemas/` with extraction and analysis output schemas unless overridden.

The main CLI can list and validate scenarios without introducing a second CLI
entry point:

```bash
python -m mmap_optimizer.cli.main list-scenarios --json
python -m mmap_optimizer.cli.main validate-scenario default --json
```
