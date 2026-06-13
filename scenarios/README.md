# Scenario directory convention

Each optimizer scenario lives under `scenarios/<scenario_id>/` and uses the following layout:

```text
scenarios/<scenario_id>/
├── optimizer.yaml
├── prompts/
├── schemas/
└── data/
```

- `optimizer.yaml` contains scenario-specific optimizer overrides.
- `prompts/` contains prompt templates or prompt text files loaded for the run.
- `schemas/` contains JSON/YAML schemas required by the scenario; at least one schema file is required.
- `data/` contains optional scenario data fixtures or inputs.

A scenario can override `model`, `sampling`, `compression`, `fewshot`, `patch_merge`, and `run_dir` values. Runtime callers can still override `run_dir` through the CLI with `--run-dir`.
