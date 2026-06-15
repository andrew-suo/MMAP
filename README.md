# MMAP Optimizer MVP

This repository contains an MVP skeleton for a multimodal prompt optimization framework. It implements the foundations discussed in the design phase:

- Prompt IR with frozen external output-schema contracts.
- Prompt rendering with section markers.
- JSON/JSONL file-based logging for reproducible optimization rounds and run-level summaries.
- Extraction evaluation with parse, schema, and primary-answer checks.
- Dynamic validation sampling instead of a fixed validation set.
- A minimal text-patch loop: analysis-output parsing, patch validation, strict individual patch tests, and PromptVersion updates.
- Conservative extraction and analysis prompt compression that runs after text optimization and accepts only behavior-preserving line reductions.
- Greedy few-shot slot optimization for stable text prompts.
- A smoke CLI that runs mock rounds and an OpenAI-compatible adapter that can send local or remote image assets as multimodal message parts.


## Design documentation

The full design record from the planning discussion is preserved in [`docs/design.md`](docs/design.md). It covers Prompt IR, Patch Schema, round state machines, dynamic validation, strict regression/poisoning, analysis-prompt evolution, compression, few-shot optimization, section contribution tracking, scenario management, checkpoint/resume, debug events, and the MVP-to-production roadmap.

## Quick smoke run

```bash
python -m mmap_optimizer.cli.main run-smoke \
  --data-dir data \
  --run-dir runs/smoke \
  --batch-size 2 \
  --dynamic-validation-batch-size 1 \
  --rounds 2 \
  --extraction-line-budget 120 \
  --fewshot-enabled
```

The smoke command loads samples, prompts, and schemas; renders prompt IRs; runs mock extraction; evaluates outputs; optionally consumes mock analysis patch outputs; writes per-round logs plus `run_summary.json`; and prints final-round metrics.

## MVP module map

- `mmap_optimizer/prompt`: Prompt IR, immutable schema contracts, rendering, initialization.
- `mmap_optimizer/evaluation`: schema validation and primary-answer evaluation.
- `mmap_optimizer/sampling`: optimization and dynamic-validation samplers.
- `mmap_optimizer/orchestration`: MVP round runner, serial optimizer loop, and run records.
- `mmap_optimizer/patch`: patch schema, validation, merge, application, and strict update foundations.
- `mmap_optimizer/testing`: strict fixed/broken transition summaries.
- `mmap_optimizer/fewshot`: few-shot candidate/example/set schemas and greedy slot optimizer.
- `mmap_optimizer/compression`: line-budget compression engine and compression report schema.
- `mmap_optimizer/storage`: JSON/JSONL persistence.
- `mmap_optimizer/model`: deterministic mock client and OpenAI-compatible multimodal client.

## Current scope

This implementation slice focuses on stable data models, logging, prompt rendering, evaluation, dynamic validation, and a runnable text-patch round skeleton. Analysis outputs can now be parsed into patch candidates, each candidate is applied to a temporary PromptVersion for model-backed testing, and accepted patches can update the active extraction PromptVersion after strict tests. If extraction or analysis line budgets are configured, the round then tries conservative compression on mutable sections and promotes only candidates that preserve baseline extraction predictions/statuses or parsed analysis outputs on the behavior suite. Full production LLM prompt engineering for patch generation and unified analysis-prompt patch testing remain next implementation steps.


## Mock prompt-dependent outputs

Tests and smoke data can keep model calls deterministic while still exercising temporary PromptVersion rendering. A sample may provide `metadata.mock_prompt_outputs` rules; `MockModelClient` returns the first rule whose `contains` text appears in the rendered system prompt, otherwise it falls back to `metadata.mock_output`. This allows patch tests to validate the real apply-render-run-evaluate path without external API calls.


## Tree-reduce patch merge and bundle safety

Before patch testing, candidate patches are clustered by target prompt, section, and operation; duplicates and subsumed patches are removed while preserving source trace; obvious conflicts such as OK-vs-NG label bias, strict-vs-relaxed guidance, frozen targets, and delete/add operation conflicts are rejected. The merge report is written to `round_xxxxxx/patches/merge_report.json`. Each merged patch is then tested individually, and individually accepted patches are re-tested as a bundle before they can update the active extraction prompt. If the full bundle is toxic, the round runner performs greedy safe-subset selection: patches are tried in descending fixed-sample count order, and any patch that introduces bundle-level toxicity is rejected with a bundle rejection reason.

## Prompt template registry and patch locator alignment

The optimizer now has a versioned prompt-template registry for production LLM-assisted steps that remain gated by deterministic parsing, validation, and behavior tests. The bundled templates cover patch locator translation, text matching, JSON repair fallback, semantic patch merge/root audit, section rewrite, LLM pruning and prune validation, numbering-only refactor, prompt format repair, and lossless prompt standardization. A deterministic patch alignment helper can calibrate legacy/free-form locator fields (`target_section`, `section_id`, `old_text`, and `target_text`) against the current PromptIR while preserving payload fields such as `content`, `patch_text`, `new_text`, and `reasoning` byte-for-byte. Optional feature flags can route analysis parsing through LLM JSON repair, route tree-reduced patches through semantic merge/root audit before validation, and let compression attempt LLM pruning plus semantic validation before the existing behavior-preservation gate. Text-level patch modes (`replace_in_section`, `insert_after`, and `insert_before`) now fail closed when locators do not match. Supporting production-readiness utilities cover section contribution scoring, no-GT eval voting, run-state checkpoints, prompt snapshots/health checks, ordered concurrency, scenario loading, patch repair, and debug JSONL events.


## Analysis output parsing and repair

Analysis model outputs are parsed through a production-oriented parser before any patch enters the patch workflow. The parser strips common markdown fences, extracts embedded JSON objects from surrounding text, validates the required analysis fields, and validates each patch candidate independently. Malformed analysis records are still persisted with parse/schema errors, while invalid patch candidates are counted and filtered out instead of aborting the round. Round metrics include analysis parse success rate, analysis schema valid rate, judgement-match rate, and valid patch candidate rate.


## Analysis prompt evolution

The MVP now promotes analysis prompt candidates from deterministic hard-failure signals rather than from self-certifying analysis text. Schema/frozen-target patch violations add schema-guard guidance, and toxic patch results add risk-policy self-check guidance. Candidate analysis prompts pass a simple shadow gate before becoming the active analysis prompt for subsequent rounds.


## Configurable model clients

Use `python -m mmap_optimizer.cli.main run --config configs/optimizer.yaml` for configurable model clients. The optimizer config has separate `models.extraction` and `models.optimizer` blocks, so the multimodal extraction model and backend analysis/optimization model can use different OpenAI-compatible URLs, API keys, and model names. Set `provider: openai_compatible`, `base_url`, `model`, and either `api_key_env` or `api_key`; keeping API keys in environment variables is recommended. The lower-level `RoundRunner` also accepts separate `extraction_client` and `optimizer_client` objects while retaining `model_client` as a backward-compatible single-client fallback.


## OpenAI-compatible multimodal calls

`OpenAICompatibleClient.complete_multimodal()` now converts `SampleAsset` images into OpenAI-compatible `image_url` message parts. Local images are embedded as `data:<mime>;base64,...` URLs, remote `uri` values are passed through directly, and optional `asset.metadata["openai_image_detail"]` is forwarded as the image detail setting. Non-string user content is serialized as a text part so the existing structured sample context can be sent alongside one or more images.


## Serial optimization loop

`OptimizerLoop` runs `RoundRunner` for the configured lifecycle instead of requiring callers to invoke one round at a time. By default it plans `max_text_rounds` plus configured few-shot rounds when few-shot is enabled; callers can override this with `--rounds` in the smoke CLI or `max_rounds` in code. The loop deliberately does not early-stop when a text round accepts no extraction patches, because analysis-prompt evolution, difficulty updates, compression, and later few-shot phases still need deterministic round accounting. It persists aggregate progress to `run_summary.json`, including round ids, final prompt versions, first/final/best accuracies, and total accepted/rejected/toxic/compression/few-shot counts.


## Compression protocol

Set `OptimizerConfig.extraction_line_budget` / `OptimizerConfig.analysis_line_budget` or pass `--extraction-line-budget` / `--analysis-line-budget` in smoke mode to enable post-round prompt compression. The MVP compressor skips frozen schema sections, ranks mutable compressible sections, removes blank and duplicate lines from one section at a time, and runs a behavior-preservation gate before promotion. Extraction compression rejects candidates that introduce parse/schema errors, change normalized predictions, or change baseline evaluation statuses; analysis compression reruns the analysis behavior suite and rejects candidates whose parsed analysis output changes. Reports are written under `round_xxxxxx/reports/compression_<round>_<prompt_type>.json`, and behavior-test runs are written under `round_xxxxxx/runs/compression_runs.jsonl`.


## Few-shot optimization protocol

Set `OptimizerConfig.fewshot_enabled` or pass `--fewshot-enabled` to run few-shot optimization after text rounds have completed (`round_index > max_text_rounds`). The miner records failed samples in a persistent `fewshot_candidate_pool.json`, ranks current and historical candidates by difficulty/gain, generates schema-complete examples with analysis-process text (using sample overrides or the optimizer model), then either adds an empty slot or replaces the lowest-index slot when capacity is full. A candidate is promoted only when individual and bundle few-shot tests improve accuracy by at least the configured delta, create no schema violations, and break no sample that was already correct. Reports are written under `round_xxxxxx/reports/fewshot_<round>_extraction.json`, and few-shot test runs are written under `round_xxxxxx/runs/fewshot_runs.jsonl`.

## Cross-round metrics trend

Every `OptimizerLoop` run now writes a `metrics_trend.json` artifact next to `run_summary.json`. The trend report keeps one point per round with absolute metrics, deltas from the previous round, best extraction/dynamic-validation rounds, aggregate patch/merge counts, and regression round ids. This is designed for the non-fixed validation strategy: a dynamic-validation drop is reported separately from optimization-batch accuracy so later dashboards can distinguish sampled validation noise from direct batch regressions.


## Dynamic validation sampling

The dynamic-validation set is intentionally not fixed. Each round excludes the optimization batch, then fills a validation batch with label coverage, optional easy/medium/hard difficulty-bin coverage, and a recent-selection penalty. The persisted `dynamic_validation_batch.json` records label/difficulty composition, target coverage, coverage warnings, recent sample ids, and recent-overlap ratio so the run can be audited without pinning a permanent validation set. Configure this through `dynamic_validation.min_label_count`, `dynamic_validation.cover_difficulty_bins`, `dynamic_validation.recent_window_rounds`, and `dynamic_validation.max_recent_selections`.

## Production-readiness integrations

The command line and round runner now wire several previously standalone helpers into the main flow:

- `run` and `run-smoke` accept `--scenario <dir>`; a scenario directory can provide `optimizer.yaml`, `data/`, `prompts/`, and `schemas/` so task-specific runs do not need long path lists.
- `check-prompt` performs prompt health validation without starting a run, and every optimization round writes extraction/analysis health reports before sampling. ERROR-level health issues abort the round before any model calls or prompt mutations.
- Prompt snapshots are saved automatically before accepted patches mutate the active extraction prompt, and run progress is checkpointed to `run_state.json` at initialization, round start, round completion, and final completion.
- No-GT samples can be evaluated through the integrated voting path: the prompt runner executes multiple extraction calls, and `Evaluator.evaluate_without_ground_truth()` records the majority result and confidence in the evaluation `extra` payload.
- `execution.max_workers` controls ordered concurrent sample execution for extraction and validation batches. Section contribution reports are persisted per round and feed high-risk section signals back into sample fragility scores for later dynamic-validation sampling.

## Prompt quality and template hardening

The bundled raw prompts now provide stronger extraction and analysis instructions, including explicit role/task scope, CORRECT/INCORRECT/UNCERTAIN definitions, no-hallucination rules, boundary-case handling, schema-oriented output guidance, and patch quality criteria. Optimizer templates are versioned with richer output contracts, embedded examples for semantic merge/root audit/prune validation/JSON repair, a dedicated patch-generation template, and a prompt self-check template for placeholder, contradiction, and schema-alignment audits. Patch locator alignment also records fuzzy-match score and character positions while marking unresolved locators in `extra.unresolved_locators` for manual or LLM-assisted follow-up.

For candidate prompt upgrades, `mmap_optimizer.prompt.ab_test.run_prompt_ab_test()` runs old/new PromptVersions over the same sample slice and promotes only non-regressing candidates that meet the configured accuracy delta.
