# MMAP Optimizer MVP

This repository contains an MVP skeleton for a multimodal prompt optimization framework. It implements the foundations discussed in the design phase:

- Prompt IR with frozen external output-schema contracts.
- Prompt rendering with section markers.
- JSON/JSONL file-based logging for reproducible optimization rounds and run-level summaries.
- Extraction evaluation with parse, schema, and primary-answer checks.
- Dynamic validation sampling instead of a fixed validation set.
- A minimal text-patch loop: analysis-output parsing, patch validation, strict individual patch tests, and PromptVersion updates.
- Conservative extraction prompt compression that runs after text optimization and accepts only behavior-preserving line reductions.
- Greedy few-shot slot optimization for stable text prompts.
- A smoke CLI that runs mock rounds and an OpenAI-compatible adapter that can send local or remote image assets as multimodal message parts.

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

This implementation slice focuses on stable data models, logging, prompt rendering, evaluation, dynamic validation, and a runnable text-patch round skeleton. Analysis outputs can now be parsed into patch candidates, each candidate is applied to a temporary PromptVersion for model-backed testing, and accepted patches can update the active extraction PromptVersion after strict tests. If an extraction line budget is configured, the round then tries conservative compression on mutable sections and promotes only candidates that preserve baseline predictions/statuses on the behavior suite. Full production LLM prompt engineering for patch generation, analysis-prompt compression, and multi-round few-shot search remain next implementation steps.


## Mock prompt-dependent outputs

Tests and smoke data can keep model calls deterministic while still exercising temporary PromptVersion rendering. A sample may provide `metadata.mock_prompt_outputs` rules; `MockModelClient` returns the first rule whose `contains` text appears in the rendered system prompt, otherwise it falls back to `metadata.mock_output`. This allows patch tests to validate the real apply-render-run-evaluate path without external API calls.


## Bundle safety

Each individually accepted patch is now re-tested as part of an accepted-patch bundle before it can update the active extraction prompt. If the full bundle is toxic, the round runner performs greedy safe-subset selection: patches are tried in descending fixed-sample count order, and any patch that introduces bundle-level toxicity is rejected with a bundle rejection reason.


## Analysis prompt evolution

The MVP now promotes analysis prompt candidates from deterministic hard-failure signals rather than from self-certifying analysis text. Schema/frozen-target patch violations add schema-guard guidance, and toxic patch results add risk-policy self-check guidance. Candidate analysis prompts pass a simple shadow gate before becoming the active analysis prompt for subsequent rounds.


## OpenAI-compatible multimodal calls

`OpenAICompatibleClient.complete_multimodal()` now converts `SampleAsset` images into OpenAI-compatible `image_url` message parts. Local images are embedded as `data:<mime>;base64,...` URLs, remote `uri` values are passed through directly, and optional `asset.metadata["openai_image_detail"]` is forwarded as the image detail setting. Non-string user content is serialized as a text part so the existing structured sample context can be sent alongside one or more images.


## Serial optimization loop

`OptimizerLoop` runs `RoundRunner` for the configured lifecycle instead of requiring callers to invoke one round at a time. By default it plans `max_text_rounds` plus configured few-shot rounds when few-shot is enabled; callers can override this with `--rounds` in the smoke CLI or `max_rounds` in code. The loop deliberately does not early-stop when a text round accepts no extraction patches, because analysis-prompt evolution, difficulty updates, compression, and later few-shot phases still need deterministic round accounting. It persists aggregate progress to `run_summary.json`, including round ids, final prompt versions, first/final/best accuracies, and total accepted/rejected/toxic/compression/few-shot counts.


## Compression protocol

Set `OptimizerConfig.extraction_line_budget` or pass `--extraction-line-budget` to enable post-round extraction prompt compression. The MVP compressor skips frozen schema sections, ranks mutable compressible sections, removes blank and duplicate lines from one section at a time, and runs a behavior-preservation gate before promotion. A compression candidate is rejected if it introduces parse/schema errors, changes any normalized prediction, or changes the baseline evaluation status for the sampled behavior suite. Reports are written under `round_xxxxxx/reports/compression_<round>_extraction.json`, and behavior-test runs are written under `round_xxxxxx/runs/compression_runs.jsonl`.


## Few-shot optimization protocol

Set `OptimizerConfig.fewshot_enabled` or pass `--fewshot-enabled` to run few-shot optimization after text rounds have completed (`round_index > max_text_rounds`). The MVP miner ranks currently failed samples by difficulty, generates a schema-complete example from ground truth plus an analysis-process text, appends it to a `few_shot_examples` section, and tests the temporary prompt on the current behavior suite. A slot is promoted only when it improves accuracy by at least the configured delta, creates no schema violations, and breaks no sample that was already correct. Reports are written under `round_xxxxxx/reports/fewshot_<round>_extraction.json`, and few-shot test runs are written under `round_xxxxxx/runs/fewshot_runs.jsonl`.
