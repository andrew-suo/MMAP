from __future__ import annotations

import json
from dataclasses import dataclass

from mmap_optimizer.core.config import OptimizerConfig
from mmap_optimizer.core.enums import RunType
from mmap_optimizer.analysis.runner import AnalysisRunner
from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset, SampleState
from mmap_optimizer.evaluation.evaluator import EvaluationRecord, Evaluator
from mmap_optimizer.metrics.round_metrics import RoundMetrics, compute_round_metrics
from mmap_optimizer.patch.applier import PatchApplier
from mmap_optimizer.patch.merger import PatchMerger
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.validator import PatchValidator
from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.sampling.dynamic_validation_sampler import DynamicValidationBatch, select_dynamic_validation_batch
from mmap_optimizer.sampling.optimization_sampler import select_optimization_batch
from mmap_optimizer.testing.patch_tester import PatchTestResult, summarize_patch_test
from mmap_optimizer.testing.suite_builder import PatchTestSuiteBuilder
from mmap_optimizer.storage.json_store import JsonStore
from .records import OptimizationRound, RunRecord


@dataclass
class OptimizerState:
    samples: list[Sample]
    assets: dict[str, SampleAsset]
    ground_truths: dict[str, GroundTruth]
    sample_states: dict[str, SampleState]
    active_extraction_prompt: PromptVersion
    active_analysis_prompt: PromptVersion
    extraction_output_schema_contract: OutputSchemaContract
    analysis_output_schema_contract: OutputSchemaContract


class RoundRunner:
    def __init__(self, *, model_client: ModelClient, evaluator: Evaluator, store: JsonStore, config: OptimizerConfig | None = None):
        self.model_client = model_client
        self.evaluator = evaluator
        self.store = store
        self.config = config or OptimizerConfig()

    def run_round(self, state: OptimizerState, *, round_index: int) -> tuple[OptimizationRound, RoundMetrics]:
        round_id = f"round_{round_index:06d}"
        round_record = OptimizationRound(
            id=round_id, index=round_index, status="ROUND_CREATED",
            base_extraction_prompt_version_id=state.active_extraction_prompt.id,
            base_analysis_prompt_version_id=state.active_analysis_prompt.id,
        )
        self.store.write_json(f"{round_id}/round.json", round_record)

        optimization_batch = select_optimization_batch(state.samples, state.sample_states, self.config.batch_size, round_index=round_index)
        round_record.optimization_batch_ids = [s.id for s in optimization_batch]
        dval_batch = select_dynamic_validation_batch(
            round_id=round_id, samples=state.samples, ground_truths=state.ground_truths, sample_states=state.sample_states,
            batch_size=self.config.dynamic_validation_batch_size, exclude_sample_ids=set(round_record.optimization_batch_ids), seed=round_index,
        )
        round_record.dynamic_validation_batch_id = dval_batch.id
        self.store.write_json(f"{round_id}/dynamic_validation_batch.json", dval_batch)

        extraction_runs, evals = self._run_and_evaluate_batch(
            round_id=round_id, run_type=RunType.EXTRACTION.value, samples=optimization_batch, state=state,
        )
        dynamic_samples = [s for s in state.samples if s.id in set(dval_batch.sample_ids)]
        dval_runs, dval_evals = self._run_and_evaluate_batch(
            round_id=round_id, run_type=RunType.DYNAMIC_VALIDATION_EXTRACTION.value, samples=dynamic_samples, state=state,
        )
        round_record.extraction_run_ids = [r.id for r in extraction_runs]
        round_record.dynamic_validation_run_ids = [r.id for r in dval_runs]

        extraction_by_sample = {run.sample_id: run for run in extraction_runs if run.sample_id}
        analysis_records = []
        analysis_runs = []
        draft_patches: list[Patch] = []
        candidate_patches: list[Patch] = []
        rejected_patches: list[Patch] = []
        patch_test_results: list[PatchTestResult] = []

        wrong_evals = [evaluation for evaluation in evals if evaluation.overall_status != "correct"]
        if wrong_evals:
            analysis_result = AnalysisRunner(self.model_client, model_id=self.config.optimizer_model.model).analyze_errors(
                round_id=round_id,
                error_evaluations=wrong_evals,
                extraction_runs=extraction_by_sample,
                sample_metadata={sample.id: sample.metadata for sample in state.samples},
                analysis_prompt=state.active_analysis_prompt,
            )
            analysis_records = analysis_result.analysis_records
            analysis_runs = analysis_result.analysis_runs
            draft_patches = analysis_result.draft_patches

            validator = PatchValidator()
            for patch in draft_patches:
                validation = validator.validate(patch, state.active_extraction_prompt.prompt_ir)
                if validation.valid:
                    patch.status = "candidate"
                    candidate_patches.append(patch)
                else:
                    patch.status = "rejected"
                    patch.rejection_reason = validation.reason
                    rejected_patches.append(patch)

            merged_patches = PatchMerger().merge(candidate_patches)
            accepted_patches: list[Patch] = []
            suite_builder = PatchTestSuiteBuilder()
            for patch in merged_patches:
                suite = suite_builder.build_individual_suite(round_id=round_id, patch=patch, current_evaluations=evals)
                base_suite_evals = [evaluation for evaluation in evals if evaluation.sample_id in set(suite.sample_ids)]
                patched_evals = self._evaluate_mock_patch_outputs(round_id=round_id, patch=patch, suite_sample_ids=suite.sample_ids, state=state)
                test_result = summarize_patch_test(round_id, patch.id, suite.id, base_suite_evals, patched_evals)
                patch_test_results.append(test_result)
                patch.fixed_sample_ids = test_result.fixed_sample_ids
                patch.broken_sample_ids = test_result.broken_sample_ids
                patch.toxicity_result = test_result.toxicity_result
                patch.effectiveness_result = test_result.effectiveness_result
                if test_result.accepted:
                    patch.status = "accepted"
                    accepted_patches.append(patch)
                else:
                    patch.status = "rejected"
                    patch.rejection_reason = test_result.rejection_reason
                    rejected_patches.append(patch)

            if accepted_patches:
                new_version_number = state.active_extraction_prompt.version + 1
                next_prompt = state.active_extraction_prompt
                for patch in accepted_patches:
                    next_prompt = PatchApplier().apply(next_prompt, patch, new_version=new_version_number)
                    new_version_number += 1
                state.active_extraction_prompt = next_prompt
                round_record.accepted_patch_ids = [patch.id for patch in accepted_patches]
            round_record.rejected_patch_ids = [patch.id for patch in rejected_patches]

        metrics = compute_round_metrics(round_id, evals, dval_evals)
        metrics.draft_count = len(draft_patches)
        metrics.candidate_count = len(candidate_patches)
        metrics.accepted_count = len(round_record.accepted_patch_ids)
        metrics.rejected_count = len(round_record.rejected_patch_ids)
        metrics.toxic_count = sum(1 for result in patch_test_results if result.toxicity_result == "toxic")
        metrics.ineffective_count = sum(1 for result in patch_test_results if result.effectiveness_result == "ineffective")
        round_record.round_metrics_id = metrics.id
        round_record.status = "ROUND_COMPLETED"
        self._update_sample_state(state, evals, round_index)

        self.store.append_jsonl(f"{round_id}/runs/extraction_runs.jsonl", extraction_runs)
        self.store.append_jsonl(f"{round_id}/runs/dynamic_validation_runs.jsonl", dval_runs)
        self.store.append_jsonl(f"{round_id}/runs/analysis_runs.jsonl", analysis_runs)
        self.store.append_jsonl(f"{round_id}/evaluations/evaluation_records.jsonl", evals + dval_evals)
        self.store.append_jsonl(f"{round_id}/analyses/analysis_records.jsonl", analysis_records)
        self.store.append_jsonl(f"{round_id}/patches/draft_patches.jsonl", draft_patches)
        self.store.append_jsonl(f"{round_id}/patches/patch_test_results.jsonl", patch_test_results)
        if round_record.accepted_patch_ids:
            self.store.write_json(f"{round_id}/prompts/active_extraction_prompt.json", state.active_extraction_prompt)
        self.store.write_json(f"{round_id}/metrics/round_metrics.json", metrics)
        self.store.write_json(f"{round_id}/round.json", round_record)
        return round_record, metrics

    def _run_and_evaluate_batch(self, *, round_id: str, run_type: str, samples: list[Sample], state: OptimizerState) -> tuple[list[RunRecord], list[EvaluationRecord]]:
        rendered = state.active_extraction_prompt.render()
        runs: list[RunRecord] = []
        evals: list[EvaluationRecord] = []
        for sample in samples:
            messages = [{"role": "system", "content": rendered.text}, {"role": "user", "content": {"sample_id": sample.id, "text_context": sample.text_context, "mock_output": sample.metadata.get("mock_output")}}]
            response = self.model_client.complete_multimodal(messages, [state.assets[aid] for aid in sample.asset_ids if aid in state.assets], model_config={"model": self.config.extraction_model.model})
            run = RunRecord(
                id=f"run_{round_id}_{run_type}_{sample.id}", round_id=round_id, run_type=run_type, sample_id=sample.id,
                prompt_version_id=state.active_extraction_prompt.id, rendered_prompt_hash=rendered.text_hash,
                model_id=self.config.extraction_model.model, raw_output=response.raw_output,
            )
            try:
                run.parsed_output = json.loads(response.raw_output)
            except Exception:
                run.parsed_output = None
            gt = state.ground_truths[sample.ground_truth_id]
            evaluation = self.evaluator.evaluate(
                round_id=round_id, run_id=run.id, sample_id=sample.id, raw_output=response.raw_output, ground_truth=gt, contract=state.extraction_output_schema_contract,
            )
            runs.append(run)
            evals.append(evaluation)
        return runs, evals

    def _evaluate_mock_patch_outputs(self, *, round_id: str, patch: Patch, suite_sample_ids: list[str], state: OptimizerState) -> list[EvaluationRecord]:
        samples_by_id = {sample.id: sample for sample in state.samples}
        evaluations: list[EvaluationRecord] = []
        for sample_id in suite_sample_ids:
            sample = samples_by_id[sample_id]
            patch_outputs = sample.metadata.get("mock_patch_outputs", {})
            raw_output = patch_outputs.get(patch.id) or patch_outputs.get(patch.section_id) or sample.metadata.get("mock_output")
            evaluations.append(
                self.evaluator.evaluate(
                    round_id=round_id,
                    run_id=f"run_{round_id}_patch_test_{patch.id}_{sample_id}",
                    sample_id=sample_id,
                    raw_output=raw_output,
                    ground_truth=state.ground_truths[sample.ground_truth_id],
                    contract=state.extraction_output_schema_contract,
                )
            )
        return evaluations

    def _update_sample_state(self, state: OptimizerState, evals: list[EvaluationRecord], round_index: int) -> None:
        for evaluation in evals:
            sample_state = state.sample_states.setdefault(evaluation.sample_id, SampleState(sample_id=evaluation.sample_id))
            error = 0.0 if evaluation.overall_status == "correct" else 1.0
            sample_state.difficulty_ema = 0.2 * error + 0.8 * sample_state.difficulty_ema
            sample_state.last_selected_round = round_index
            sample_state.selected_count_recent_window += 1
            if error:
                sample_state.consecutive_wrong_count += 1
                sample_state.consecutive_correct_count = 0
            else:
                sample_state.consecutive_correct_count += 1
                sample_state.consecutive_wrong_count = 0
