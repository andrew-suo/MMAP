from __future__ import annotations

from dataclasses import dataclass

from mmap_optimizer.compression.engine import CompressionEngine
from mmap_optimizer.core.config import OptimizerConfig
from mmap_optimizer.fewshot.engine import FewShotOptimizationEngine
from mmap_optimizer.core.enums import RunType
from mmap_optimizer.analysis.evolution import AnalysisEvolutionEngine
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
from mmap_optimizer.testing.patch_runner import PatchTester
from mmap_optimizer.testing.patch_tester import PatchTestResult
from mmap_optimizer.testing.prompt_test_runner import PromptTestRunner
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
    def __init__(
        self,
        *,
        evaluator: Evaluator,
        store: JsonStore,
        config: OptimizerConfig | None = None,
        model_client: ModelClient | None = None,
        extraction_client: ModelClient | None = None,
        optimizer_client: ModelClient | None = None,
    ):
        fallback_client = model_client or extraction_client or optimizer_client
        if fallback_client is None:
            raise ValueError("RoundRunner requires model_client or extraction_client/optimizer_client")
        self.extraction_client = extraction_client or fallback_client
        self.optimizer_client = optimizer_client or fallback_client
        self.model_client = fallback_client  # Backward-compatible alias for existing tests/extensions.
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

        extraction_result = self._prompt_runner().run(
            round_id=round_id,
            run_type=RunType.EXTRACTION.value,
            prompt=state.active_extraction_prompt,
            samples=optimization_batch,
            assets=state.assets,
            ground_truths=state.ground_truths,
            contract=state.extraction_output_schema_contract,
        )
        extraction_runs, evals = extraction_result.runs, extraction_result.evaluations
        dynamic_samples = [s for s in state.samples if s.id in set(dval_batch.sample_ids)]
        dval_result = self._prompt_runner().run(
            round_id=round_id,
            run_type=RunType.DYNAMIC_VALIDATION_EXTRACTION.value,
            prompt=state.active_extraction_prompt,
            samples=dynamic_samples,
            assets=state.assets,
            ground_truths=state.ground_truths,
            contract=state.extraction_output_schema_contract,
        )
        dval_runs, dval_evals = dval_result.runs, dval_result.evaluations
        round_record.extraction_run_ids = [r.id for r in extraction_runs]
        round_record.dynamic_validation_run_ids = [r.id for r in dval_runs]

        extraction_by_sample = {run.sample_id: run for run in extraction_runs if run.sample_id}
        analysis_records = []
        analysis_runs = []
        draft_patches: list[Patch] = []
        candidate_patches: list[Patch] = []
        rejected_patches: list[Patch] = []
        patch_test_results: list[PatchTestResult] = []
        patch_test_runs = []
        patch_test_evals = []
        compression_reports = []
        compression_runs = []
        compression_evals = []
        fewshot_reports = []
        fewshot_runs = []
        fewshot_evals = []

        wrong_evals = [evaluation for evaluation in evals if evaluation.overall_status != "correct"]
        if wrong_evals:
            analysis_result = AnalysisRunner(self.optimizer_client, model_id=self.config.optimizer_model.model).analyze_errors(
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
            patch_tester = PatchTester(model_client=self.extraction_client, evaluator=self.evaluator, model_id=self.config.extraction_model.model)
            for patch in merged_patches:
                suite = suite_builder.build_individual_suite(round_id=round_id, patch=patch, current_evaluations=evals)
                base_suite_evals = [evaluation for evaluation in evals if evaluation.sample_id in set(suite.sample_ids)]
                patch_run = patch_tester.test_individual(
                    round_id=round_id,
                    patch=patch,
                    base_prompt=state.active_extraction_prompt,
                    base_evaluations=base_suite_evals,
                    suite=suite,
                    samples=state.samples,
                    assets=state.assets,
                    ground_truths=state.ground_truths,
                    contract=state.extraction_output_schema_contract,
                )
                test_result = patch_run.test_result
                patch_test_runs.extend(patch_run.runs)
                patch_test_evals.extend(patch_run.evaluations)
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

            final_patches: list[Patch] = []
            if accepted_patches:
                final_patches, bundle_runs, bundle_evals, bundle_results = self._select_safe_bundle(
                    round_id=round_id,
                    accepted_patches=accepted_patches,
                    patch_tester=patch_tester,
                    suite_builder=suite_builder,
                    base_prompt=state.active_extraction_prompt,
                    base_evaluations=evals,
                    state=state,
                )
                patch_test_runs.extend(bundle_runs)
                patch_test_evals.extend(bundle_evals)
                patch_test_results.extend(bundle_results)
                rejected_patches.extend([patch for patch in accepted_patches if patch not in final_patches])

            if final_patches:
                next_prompt = state.active_extraction_prompt
                next_version = next_prompt.version + 1
                for patch in final_patches:
                    next_prompt = PatchApplier().apply(next_prompt, patch, new_version=next_version)
                    next_version += 1
                state.active_extraction_prompt = next_prompt
                round_record.accepted_patch_ids = [patch.id for patch in final_patches]
            round_record.rejected_patch_ids = [patch.id for patch in rejected_patches]

        analysis_evolution_report = AnalysisEvolutionEngine().evolve(
            round_id=round_id,
            current_prompt=state.active_analysis_prompt,
            rejected_patches=rejected_patches,
            patch_test_results=patch_test_results,
        )
        round_record.analysis_evolution_report_id = analysis_evolution_report.id
        if analysis_evolution_report.promoted and analysis_evolution_report.candidate_prompt is not None:
            state.active_analysis_prompt = analysis_evolution_report.candidate_prompt

        compression_engine = CompressionEngine(
            model_client=self.extraction_client,
            evaluator=self.evaluator,
            model_id=self.config.extraction_model.model,
        )
        compressed_prompt, compression_report, compression_runs, compression_evals = compression_engine.compress_if_needed(
            round_id=round_id,
            prompt=state.active_extraction_prompt,
            line_budget=self.config.extraction_line_budget,
            samples=optimization_batch,
            assets=state.assets,
            ground_truths=state.ground_truths,
            contract=state.extraction_output_schema_contract,
            base_evaluations=evals,
        )
        compression_reports.append(compression_report)
        round_record.compression_report_ids = [report.id for report in compression_reports]
        if compression_report.accepted:
            state.active_extraction_prompt = compressed_prompt

        fewshot_round_index = round_index - self.config.max_text_rounds
        if self.config.fewshot_enabled and 0 < fewshot_round_index <= self.config.fewshot_max_rounds:
            fewshot_engine = FewShotOptimizationEngine(
                model_client=self.extraction_client,
                evaluator=self.evaluator,
                model_id=self.config.extraction_model.model,
            )
            fewshot_prompt, fewshot_report, fewshot_runs, fewshot_evals = fewshot_engine.optimize_once(
                round_id=round_id,
                prompt=state.active_extraction_prompt,
                samples=optimization_batch,
                assets=state.assets,
                ground_truths=state.ground_truths,
                sample_states=state.sample_states,
                contract=state.extraction_output_schema_contract,
                base_evaluations=evals,
                max_slots=self.config.fewshot_max_slots,
                min_accuracy_delta=self.config.fewshot_min_accuracy_delta,
            )
            fewshot_reports.append(fewshot_report)
            round_record.fewshot_report_ids = [report.id for report in fewshot_reports]
            if fewshot_report.accepted:
                state.active_extraction_prompt = fewshot_prompt

        metrics = compute_round_metrics(round_id, evals, dval_evals)
        metrics.draft_count = len(draft_patches)
        metrics.candidate_count = len(candidate_patches)
        metrics.accepted_count = len(round_record.accepted_patch_ids)
        metrics.rejected_count = len(round_record.rejected_patch_ids)
        metrics.toxic_count = sum(1 for result in patch_test_results if result.toxicity_result == "toxic")
        metrics.ineffective_count = sum(1 for result in patch_test_results if result.effectiveness_result == "ineffective")
        metrics.compression_triggered = any(report.triggered for report in compression_reports)
        metrics.compression_accepted = any(report.accepted for report in compression_reports)
        metrics.compression_line_reduction = sum(report.line_reduction for report in compression_reports)
        metrics.fewshot_triggered = any(report.triggered for report in fewshot_reports)
        metrics.fewshot_accepted = any(report.accepted for report in fewshot_reports)
        metrics.fewshot_accuracy_delta = sum(report.accuracy_delta for report in fewshot_reports)
        round_record.round_metrics_id = metrics.id
        round_record.status = "ROUND_COMPLETED"
        self._update_sample_state(state, evals, round_index)

        self.store.append_jsonl(f"{round_id}/runs/extraction_runs.jsonl", extraction_runs)
        self.store.append_jsonl(f"{round_id}/runs/dynamic_validation_runs.jsonl", dval_runs)
        self.store.append_jsonl(f"{round_id}/runs/analysis_runs.jsonl", analysis_runs)
        self.store.append_jsonl(f"{round_id}/runs/patch_test_runs.jsonl", patch_test_runs)
        self.store.append_jsonl(f"{round_id}/runs/compression_runs.jsonl", compression_runs)
        self.store.append_jsonl(f"{round_id}/runs/fewshot_runs.jsonl", fewshot_runs)
        self.store.append_jsonl(f"{round_id}/evaluations/evaluation_records.jsonl", evals + dval_evals + patch_test_evals + compression_evals + fewshot_evals)
        self.store.append_jsonl(f"{round_id}/analyses/analysis_records.jsonl", analysis_records)
        self.store.append_jsonl(f"{round_id}/patches/draft_patches.jsonl", draft_patches)
        self.store.append_jsonl(f"{round_id}/patches/patch_test_results.jsonl", patch_test_results)
        self.store.write_json(f"{round_id}/reports/analysis_evolution_report.json", analysis_evolution_report)
        for compression_report in compression_reports:
            self.store.write_json(f"{round_id}/reports/{compression_report.id}.json", compression_report)
        for fewshot_report in fewshot_reports:
            self.store.write_json(f"{round_id}/reports/{fewshot_report.id}.json", fewshot_report)
        if round_record.accepted_patch_ids or any(report.accepted for report in compression_reports) or any(report.accepted for report in fewshot_reports):
            self.store.write_json(f"{round_id}/prompts/active_extraction_prompt.json", state.active_extraction_prompt)
        self.store.write_json(f"{round_id}/metrics/round_metrics.json", metrics)
        self.store.write_json(f"{round_id}/round.json", round_record)
        return round_record, metrics


    def _select_safe_bundle(
        self,
        *,
        round_id: str,
        accepted_patches: list[Patch],
        patch_tester: PatchTester,
        suite_builder: PatchTestSuiteBuilder,
        base_prompt: PromptVersion,
        base_evaluations: list[EvaluationRecord],
        state: OptimizerState,
    ) -> tuple[list[Patch], list[RunRecord], list[EvaluationRecord], list[PatchTestResult]]:
        runs: list[RunRecord] = []
        evaluations: list[EvaluationRecord] = []
        results: list[PatchTestResult] = []
        all_suite = suite_builder.build_bundle_suite(round_id=round_id, patches=accepted_patches, current_evaluations=base_evaluations)
        all_base_evals = [evaluation for evaluation in base_evaluations if evaluation.sample_id in set(all_suite.sample_ids)]
        all_bundle = patch_tester.test_bundle(
            round_id=round_id,
            patches=accepted_patches,
            base_prompt=base_prompt,
            base_evaluations=all_base_evals,
            suite=all_suite,
            samples=state.samples,
            assets=state.assets,
            ground_truths=state.ground_truths,
            contract=state.extraction_output_schema_contract,
        )
        runs.extend(all_bundle.runs)
        evaluations.extend(all_bundle.evaluations)
        results.append(all_bundle.test_result)
        if all_bundle.test_result.accepted:
            return accepted_patches, runs, evaluations, results

        safe: list[Patch] = []
        for patch in sorted(accepted_patches, key=lambda item: len(item.fixed_sample_ids), reverse=True):
            trial = [*safe, patch]
            trial_suite = suite_builder.build_bundle_suite(round_id=round_id, patches=trial, current_evaluations=base_evaluations)
            trial_base_evals = [evaluation for evaluation in base_evaluations if evaluation.sample_id in set(trial_suite.sample_ids)]
            trial_bundle = patch_tester.test_bundle(
                round_id=round_id,
                patches=trial,
                base_prompt=base_prompt,
                base_evaluations=trial_base_evals,
                suite=trial_suite,
                samples=state.samples,
                assets=state.assets,
                ground_truths=state.ground_truths,
                contract=state.extraction_output_schema_contract,
            )
            runs.extend(trial_bundle.runs)
            evaluations.extend(trial_bundle.evaluations)
            results.append(trial_bundle.test_result)
            if trial_bundle.test_result.accepted:
                safe = trial
            else:
                patch.status = "rejected"
                patch.rejection_reason = "BUNDLE_TOXIC" if trial_bundle.test_result.toxicity_result == "toxic" else "BUNDLE_INEFFECTIVE"
        return safe, runs, evaluations, results

    def _prompt_runner(self) -> PromptTestRunner:
        return PromptTestRunner(model_client=self.extraction_client, evaluator=self.evaluator, model_id=self.config.extraction_model.model)

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
