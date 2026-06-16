from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field

from mmap_optimizer.compression.engine import CompressionEngine
from mmap_optimizer.core.config import OptimizerConfig, model_config_to_request_dict
from mmap_optimizer.fewshot.engine import FewShotOptimizationEngine
from mmap_optimizer.fewshot.pool import FewShotCandidatePool
from mmap_optimizer.core.enums import RunType
from mmap_optimizer.analysis.evolution import AnalysisEvolutionEngine
from mmap_optimizer.analysis.runner import AnalysisRunner
from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset, SampleState
from mmap_optimizer.debug.logger import DebugEventLogger
from mmap_optimizer.evaluation.evaluator import EvaluationRecord, Evaluator
from mmap_optimizer.logging import get_logger, log_stage
from mmap_optimizer.metrics.round_metrics import RoundMetrics, compute_round_metrics
from mmap_optimizer.metrics.section_contribution import build_section_contribution
from mmap_optimizer.patch.applier import PatchApplier
from mmap_optimizer.patch.merge_report import PatchMergeReport
from mmap_optimizer.patch.repair import PatchRepairEngine
from mmap_optimizer.patch.semantic import SemanticPatchProcessor
from mmap_optimizer.patch.tree_reduce import TreeReducePatchMerger
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.validator import PatchValidator
from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.health import check_prompt_health
from mmap_optimizer.prompt.snapshot import save_prompt_snapshot
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.sampling.dynamic_validation_sampler import DynamicValidationBatch, select_dynamic_validation_batch
from mmap_optimizer.sampling.optimization_sampler import select_optimization_batch
from mmap_optimizer.testing.patch_runner import PatchTester
from mmap_optimizer.testing.patch_tester import PatchTestResult
from mmap_optimizer.testing.prompt_test_runner import PromptTestRunner
from mmap_optimizer.testing.suite_builder import PatchTestSuiteBuilder
from mmap_optimizer.testing.transition import classify_transition
from mmap_optimizer.storage.json_store import JsonStore
from .records import OptimizationRound, RoundStage, RunRecord

logger = get_logger(__name__)


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


@dataclass
class _RegressionCheckResult:
    regression_count: int = 0
    regression_sample_ids: list[str] = field(default_factory=list)


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
        self.debug_logger = DebugEventLogger(self.store) if self.config.debug_enabled else None

    def run_round(self, state: OptimizerState, *, round_index: int) -> tuple[OptimizationRound, RoundMetrics]:
        round_id = f"round_{round_index:06d}"
        round_record = OptimizationRound(
            id=round_id, index=round_index, status="ROUND_CREATED",
            base_extraction_prompt_version_id=state.active_extraction_prompt.id,
            base_analysis_prompt_version_id=state.active_analysis_prompt.id,
        )
        self.store.write_json(f"{round_id}/round.json", round_record)
        if self.config.prompt_health_check_enabled:
            for prompt_name, prompt in [("extraction", state.active_extraction_prompt), ("analysis", state.active_analysis_prompt)]:
                health_report = check_prompt_health(prompt.prompt_ir)
                self.store.write_json(f"{round_id}/health/{prompt_name}_prompt_health.json", health_report)
                if not health_report.ok:
                    round_record.status = "ROUND_ABORTED"
                    round_record.failure_reason = f"{prompt_name.upper()}_PROMPT_HEALTH_ERROR"
                    self.store.write_json(f"{round_id}/round.json", round_record)
                    self._debug("guardrail_detention", round_id=round_id, prompt=prompt_name, issues=[issue.__dict__ for issue in health_report.issues])
                    raise ValueError(round_record.failure_reason)

        optimization_batch = select_optimization_batch(state.samples, state.sample_states, self.config.batch_size, round_index=round_index)
        round_record.optimization_batch_ids = [s.id for s in optimization_batch]
        dval_batch = select_dynamic_validation_batch(
            round_id=round_id, samples=state.samples, ground_truths=state.ground_truths, sample_states=state.sample_states,
            batch_size=self.config.dynamic_validation_batch_size,
            exclude_sample_ids=set(round_record.optimization_batch_ids),
            seed=round_index,
            round_index=round_index,
            min_label_count=self.config.dynamic_validation_min_label_count,
            cover_difficulty_bins=self.config.dynamic_validation_cover_difficulty_bins,
            recent_window_rounds=self.config.dynamic_validation_recent_window_rounds,
            max_recent_selections=self.config.dynamic_validation_max_recent_selections,
        )
        round_record.dynamic_validation_batch_id = dval_batch.id
        self.store.write_json(f"{round_id}/dynamic_validation_batch.json", dval_batch)
        log_stage(logger, "batch_selection_done", round=round_index, optimization_batch_size=len(optimization_batch), dval_batch_size=len(dval_batch.sample_ids))

        log_stage(logger, "extraction_run_start", round=round_index, sample_count=len(optimization_batch))
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
        log_stage(logger, "extraction_run_done", round=round_index, sample_count=len(optimization_batch), evaluation_count=len(evals))
        log_stage(logger, "dval_run_start", round=round_index, sample_count=len(dynamic_samples))
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
        log_stage(logger, "dval_run_done", round=round_index, sample_count=len(dynamic_samples), evaluation_count=len(dval_evals))
        round_record.extraction_run_ids = [r.id for r in extraction_runs]
        round_record.dynamic_validation_run_ids = [r.id for r in dval_runs]
        self._advance_stage(round_id, round_record, RoundStage.BASELINE_EVAL.value)
        self._save_intermediate(round_id, "extraction_done", {
            "extraction_run_ids": round_record.extraction_run_ids,
            "dynamic_validation_run_ids": round_record.dynamic_validation_run_ids,
            "eval_count": len(evals),
            "dval_eval_count": len(dval_evals),
        })

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
        merge_report: PatchMergeReport | None = None

        wrong_evals = [evaluation for evaluation in evals if evaluation.overall_status != "correct"]
        if wrong_evals:
            log_stage(logger, "patch_generation_start", round=round_index, failed_sample_count=len(wrong_evals))
            analysis_result = AnalysisRunner(
                self.optimizer_client,
                model_id=self.config.optimizer_model.model,
                model_config=self._optimizer_model_config(),
                enable_json_repair=self.config.analysis_json_repair_enabled,
                json_repair_max_attempts=self.config.analysis_json_repair_max_attempts,
            ).analyze_errors(
                round_id=round_id,
                error_evaluations=wrong_evals,
                extraction_runs=extraction_by_sample,
                sample_metadata={sample.id: sample.metadata for sample in state.samples},
                analysis_prompt=state.active_analysis_prompt,
                target_prompt=state.active_extraction_prompt,
            )
            analysis_records = analysis_result.analysis_records
            analysis_runs = analysis_result.analysis_runs
            draft_patches = analysis_result.draft_patches

            validator = PatchValidator()
            repair_engine = PatchRepairEngine(
                model_client=self.optimizer_client if self.config.patch_repair_enabled else None,
                model_config=self._optimizer_model_config(),
            )
            for patch in draft_patches:
                validation = validator.validate(patch, state.active_extraction_prompt.prompt_ir)
                if not validation.valid and self.config.patch_repair_enabled:
                    repair_result = repair_engine.repair_locator(
                        patch=asdict(patch),
                        prompt_ir=state.active_extraction_prompt.prompt_ir,
                        failure_info=validation.reason or "validation_failed",
                    )
                    repaired_patch = Patch(**repair_result.repaired_patch)
                    repaired_validation = validator.validate(repaired_patch, state.active_extraction_prompt.prompt_ir)
                    repaired_patch.extra["repair_attempts"] = 1
                    repaired_patch.extra["repair_unresolved_fields"] = repair_result.unresolved_fields
                    repaired_patch.extra["original_patch_id"] = patch.id
                    self._debug("patch_repair", round_id=round_id, patch_id=patch.id, repaired=repaired_validation.valid, reason=repaired_validation.reason, unresolved_fields=repair_result.unresolved_fields)
                    if repaired_validation.valid:
                        patch = repaired_patch
                        validation = repaired_validation
                if validation.valid:
                    patch.status = "candidate"
                    candidate_patches.append(patch)
                else:
                    patch.status = "rejected"
                    patch.rejection_reason = validation.reason
                    rejected_patches.append(patch)
                    self._debug("guardrail_detention", round_id=round_id, patch_id=patch.id, reason=validation.reason)

            self._advance_stage(round_id, round_record, RoundStage.PATCH_VALIDATION.value)
            self._save_intermediate(round_id, "patch_generation_done", {
                "draft_patch_count": len(draft_patches),
                "candidate_patch_count": len(candidate_patches),
                "rejected_patch_count": len(rejected_patches),
                "analysis_record_count": len(analysis_records),
            })

            merge_result = TreeReducePatchMerger().merge(round_id=round_id, patches=candidate_patches, prompt_ir=state.active_extraction_prompt.prompt_ir)
            merge_report = merge_result.merge_report
            merged_patches = merge_result.final_patches
            rejected_patches.extend(merge_result.rejected_patches)
            log_stage(logger, "patch_merge_done", round=round_index, merged_patch_count=len(merged_patches), rejected_count=len(merge_result.rejected_patches), merge_conflicts=len(merge_report.conflict_patch_ids) if merge_report else 0)
            if merged_patches and (self.config.patch_semantic_merge_enabled or self.config.patch_root_audit_enabled):
                semantic_processor = SemanticPatchProcessor(self.optimizer_client, self._optimizer_model_config())
                if self.config.patch_semantic_merge_enabled:
                    merged_patches = semantic_processor.merge(merged_patches, state.active_extraction_prompt.prompt_ir)
                if self.config.patch_root_audit_enabled:
                    merged_patches = semantic_processor.root_audit(merged_patches, state.active_extraction_prompt.prompt_ir)
                semantic_validated: list[Patch] = []
                for patch in merged_patches:
                    validation = validator.validate(patch, state.active_extraction_prompt.prompt_ir)
                    if validation.valid:
                        semantic_validated.append(patch)
                    else:
                        patch.status = "rejected"
                        patch.rejection_reason = validation.reason
                        rejected_patches.append(patch)
                merged_patches = semantic_validated
            log_stage(logger, "patch_testing_start", round=round_index, patch_count=len(merged_patches))
            accepted_patches: list[Patch] = []
            suite_builder = PatchTestSuiteBuilder()
            patch_tester = PatchTester(model_client=self.extraction_client, evaluator=self.evaluator, model_id=self.config.extraction_model.model, model_config=self._extraction_model_config())
            canary_sample_ids = self._select_canary_samples(state.sample_states) if self.config.canary_protection_enabled else []
            historically_fixed_ids = self._collect_historically_fixed_sample_ids(state.sample_states) if self.config.historical_regression_check_enabled else []
            for patch in merged_patches:
                suite = suite_builder.build_individual_suite(round_id=round_id, patch=patch, current_evaluations=evals, canary_sample_ids=canary_sample_ids)
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
                    canary_sample_ids=canary_sample_ids,
                    historically_fixed_sample_ids=historically_fixed_ids,
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

            log_stage(logger, "patch_testing_done", round=round_index, accepted_count=len(accepted_patches), rejected_count=len(merged_patches) - len(accepted_patches))
            self._advance_stage(round_id, round_record, RoundStage.PATCH_EVAL.value)
            self._save_intermediate(round_id, "patch_eval_done", {
                "accepted_patch_ids": [p.id for p in accepted_patches],
                "rejected_patch_ids": [p.id for p in rejected_patches],
                "test_result_count": len(patch_test_results),
            })
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
                    canary_sample_ids=canary_sample_ids,
                    historically_fixed_sample_ids=historically_fixed_ids,
                )
                patch_test_runs.extend(bundle_runs)
                patch_test_evals.extend(bundle_evals)
                patch_test_results.extend(bundle_results)
                rejected_patches.extend([patch for patch in accepted_patches if patch not in final_patches])

            if final_patches:
                log_stage(logger, "patch_apply_start", round=round_index, patch_count=len(final_patches))
                pre_apply_prompt = state.active_extraction_prompt
                next_prompt = state.active_extraction_prompt
                next_version = next_prompt.version + 1
                for patch in final_patches:
                    if self.config.prompt_snapshot_enabled:
                        snapshot = save_prompt_snapshot(self.store, next_prompt, f"{round_id}_before_{patch.id}")
                        patch.extra["pre_apply_snapshot_id"] = snapshot.id
                    next_prompt = PatchApplier().apply(next_prompt, patch, new_version=next_version)
                    next_version += 1
                state.active_extraction_prompt = next_prompt
                round_record.accepted_patch_ids = [patch.id for patch in final_patches]
                log_stage(logger, "patch_apply_done", round=round_index, applied_count=len(final_patches))

                # Post-apply regression verification
                if self.config.post_apply_regression_enabled:
                    regression_result = self._post_apply_regression_check(
                        round_id=round_id,
                        new_prompt=state.active_extraction_prompt,
                        base_evaluations=evals + dval_evals,
                        state=state,
                    )
                    if regression_result.regression_count > 0:
                        log_stage(logger, "post_apply_regression_detected", round=round_index, regression_count=regression_result.regression_count, regression_sample_ids=regression_result.regression_sample_ids)
                        state.active_extraction_prompt = pre_apply_prompt
                        round_record.accepted_patch_ids = []
                        for patch in final_patches:
                            patch.status = "rejected"
                            patch.rejection_reason = "POST_APPLY_REGRESSION"
                            rejected_patches.append(patch)
                        final_patches = []
                    else:
                        log_stage(logger, "post_apply_regression_passed", round=round_index)
            round_record.rejected_patch_ids = [patch.id for patch in rejected_patches]
            self._advance_stage(round_id, round_record, RoundStage.PATCH_APPLY.value)
            self._save_intermediate(round_id, "patch_apply_done", {
                "accepted_patch_ids": round_record.accepted_patch_ids,
                "rejected_patch_ids": round_record.rejected_patch_ids,
            })

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
            model_config=self._extraction_model_config(),
            enable_llm_compression=self.config.llm_compression_enabled,
            enable_json_repair=self.config.analysis_json_repair_enabled,
            json_repair_max_attempts=self.config.analysis_json_repair_max_attempts,
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

        if self.config.analysis_line_budget is not None and not analysis_evolution_report.promoted:
            analysis_compression_engine = CompressionEngine(
                model_client=self.optimizer_client,
                evaluator=self.evaluator,
                model_id=self.config.optimizer_model.model,
                model_config=self._optimizer_model_config(),
                enable_llm_compression=self.config.llm_compression_enabled,
                enable_json_repair=self.config.analysis_json_repair_enabled,
                json_repair_max_attempts=self.config.analysis_json_repair_max_attempts,
            )
            compressed_analysis_prompt, analysis_compression_report, analysis_compression_runs, analysis_compression_evals = (
                analysis_compression_engine.compress_analysis_if_needed(
                    round_id=round_id,
                    prompt=state.active_analysis_prompt,
                    line_budget=self.config.analysis_line_budget,
                    error_evaluations=wrong_evals,
                    sample_metadata={sample.id: sample.metadata for sample in state.samples},
                    base_runs=analysis_runs,
                )
            )
            compression_reports.append(analysis_compression_report)
            compression_runs.extend(analysis_compression_runs)
            compression_evals.extend(analysis_compression_evals)
            round_record.compression_report_ids = [report.id for report in compression_reports]
            if analysis_compression_report.accepted:
                state.active_analysis_prompt = compressed_analysis_prompt

        self._advance_stage(round_id, round_record, RoundStage.COMPRESSION.value)
        self._save_intermediate(round_id, "compression_done", {
            "compression_report_count": len(compression_reports),
            "compression_accepted": any(r.accepted for r in compression_reports),
        })

        fewshot_round_index = round_index - self.config.max_text_rounds
        if self.config.fewshot_enabled and 0 < fewshot_round_index <= self.config.fewshot_max_rounds:
            fewshot_engine = FewShotOptimizationEngine(
                model_client=self.extraction_client,
                evaluator=self.evaluator,
                model_id=self.config.extraction_model.model,
                model_config=self._extraction_model_config(),
                reasoning_model_client=self.optimizer_client,
                reasoning_model_config=self._optimizer_model_config(),
            )
            pool_path = self.store.root / "fewshot_candidate_pool.json"
            fewshot_pool = FewShotCandidatePool.from_mapping(self.store.read_json("fewshot_candidate_pool.json") if pool_path.exists() else None)
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
                candidate_pool=fewshot_pool,
            )
            self.store.write_json("fewshot_candidate_pool.json", fewshot_pool)
            fewshot_reports.append(fewshot_report)
            round_record.fewshot_report_ids = [report.id for report in fewshot_reports]
            if fewshot_report.accepted:
                state.active_extraction_prompt = fewshot_prompt

        self._advance_stage(round_id, round_record, RoundStage.FEWSHOT.value)
        self._save_intermediate(round_id, "fewshot_done", {
            "fewshot_report_count": len(fewshot_reports),
            "fewshot_accepted": any(r.accepted for r in fewshot_reports),
        })

        contribution = build_section_contribution(
            patches=self._unique_patches([*draft_patches, *candidate_patches, *rejected_patches]),
            analysis_records=analysis_records,
            patch_results=patch_test_results,
        )
        if contribution:
            self.store.write_json(f"{round_id}/metrics/section_contribution.json", contribution)
            if self.config.contribution_feedback_enabled:
                self._apply_contribution_feedback(state, evals + dval_evals, contribution)

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
        metrics.fewshot_slot_count_before = max((report.slot_count_before for report in fewshot_reports), default=0)
        metrics.fewshot_slot_count_after = max((report.slot_count_after for report in fewshot_reports), default=0)
        metrics.fewshot_candidate_count = sum(report.candidate_count for report in fewshot_reports)
        metrics.fewshot_replacement_count = sum(1 for report in fewshot_reports if report.operation_type == "REPLACE_SLOT" and report.accepted)
        metrics.fewshot_rejected_candidate_count = sum(len(report.rejected_candidates) for report in fewshot_reports)
        if analysis_records:
            metrics.analysis_parse_success_rate = sum(1 for record in analysis_records if record.parse_success) / len(analysis_records)
            metrics.analysis_schema_valid_rate = sum(1 for record in analysis_records if record.schema_valid) / len(analysis_records)
            metrics.analysis_judgement_match_rate = sum(1 for record in analysis_records if record.judgement_matches_evaluator) / len(analysis_records)
            total_patch_candidates = sum(record.generated_patch_count + record.invalid_patch_candidate_count for record in analysis_records)
            metrics.valid_patch_candidate_rate = (sum(record.generated_patch_count for record in analysis_records) / total_patch_candidates) if total_patch_candidates else 0.0
        if merge_report is not None:
            metrics.merge_input_count = len(merge_report.input_patch_ids)
            metrics.merge_output_count = len(merge_report.final_patch_ids)
            metrics.merge_conflict_count = len(merge_report.conflict_patch_ids)
            metrics.merge_duplicate_count = len(merge_report.duplicate_patch_ids)
        round_record.round_metrics_id = metrics.id
        round_record.status = "ROUND_COMPLETED"
        self._update_sample_state(state, evals + dval_evals, round_index)
        self._advance_stage(round_id, round_record, RoundStage.COMPLETED.value)

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
        if merge_report is not None:
            self.store.write_json(f"{round_id}/patches/merge_report.json", merge_report)
        self.store.write_json(f"{round_id}/reports/analysis_evolution_report.json", analysis_evolution_report)
        for compression_report in compression_reports:
            self.store.write_json(f"{round_id}/reports/{compression_report.id}.json", compression_report)
        for fewshot_report in fewshot_reports:
            self.store.write_json(f"{round_id}/reports/{fewshot_report.id}.json", fewshot_report)
        if round_record.accepted_patch_ids or any(report.accepted for report in compression_reports) or any(report.accepted for report in fewshot_reports):
            self.store.write_json(f"{round_id}/prompts/active_extraction_prompt.json", state.active_extraction_prompt)
        self.store.write_json(f"{round_id}/metrics/round_metrics.json", metrics)
        self.store.write_json(f"{round_id}/round.json", round_record)
        self._cleanup_intermediate(round_id)
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
        canary_sample_ids: list[str] | None = None,
        historically_fixed_sample_ids: list[str] | None = None,
    ) -> tuple[list[Patch], list[RunRecord], list[EvaluationRecord], list[PatchTestResult]]:
        runs: list[RunRecord] = []
        evaluations: list[EvaluationRecord] = []
        results: list[PatchTestResult] = []
        all_suite = suite_builder.build_bundle_suite(round_id=round_id, patches=accepted_patches, current_evaluations=base_evaluations, canary_sample_ids=canary_sample_ids)
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
            canary_sample_ids=canary_sample_ids,
            historically_fixed_sample_ids=historically_fixed_sample_ids,
        )
        runs.extend(all_bundle.runs)
        evaluations.extend(all_bundle.evaluations)
        results.append(all_bundle.test_result)
        if all_bundle.test_result.accepted:
            return accepted_patches, runs, evaluations, results

        safe: list[Patch] = []
        for patch in sorted(accepted_patches, key=lambda item: len(item.fixed_sample_ids), reverse=True):
            trial = [*safe, patch]
            trial_suite = suite_builder.build_bundle_suite(round_id=round_id, patches=trial, current_evaluations=base_evaluations, canary_sample_ids=canary_sample_ids)
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
                canary_sample_ids=canary_sample_ids,
                historically_fixed_sample_ids=historically_fixed_sample_ids,
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
        return PromptTestRunner(
            model_client=self.extraction_client,
            evaluator=self.evaluator,
            model_id=self.config.extraction_model.model,
            model_config=self._extraction_model_config(),
            max_workers=self.config.execution_max_workers,
            vote_rounds=self.config.eval_vote_rounds,
            enable_voting=self.config.eval_voting_enabled,
        )

    def _extraction_model_config(self) -> dict:
        return model_config_to_request_dict(self.config.extraction_model)

    def _optimizer_model_config(self) -> dict:
        return model_config_to_request_dict(self.config.optimizer_model)

    def _debug(self, event_type: str, **payload) -> None:
        if self.debug_logger is not None:
            self.debug_logger.log(event_type, payload)

    def _unique_patches(self, patches: list[Patch]) -> list[Patch]:
        by_id: dict[str, Patch] = {}
        for patch in patches:
            by_id[patch.id] = patch
        return list(by_id.values())

    def _save_intermediate(self, round_id: str, stage: str, data: dict) -> None:
        """Save intermediate results after each stage for crash recovery."""
        self.store.write_json(f"{round_id}/intermediate/{stage}.json", data)

    def _advance_stage(self, round_id: str, round_record: OptimizationRound, stage: str) -> None:
        """Update current_stage and persist round_record for crash recovery."""
        round_record.current_stage = stage
        self.store.write_json(f"{round_id}/round.json", round_record)

    def _cleanup_intermediate(self, round_id: str) -> None:
        """Remove intermediate files after a round completes successfully."""
        intermediate_dir = self.store.root / round_id / "intermediate"
        if intermediate_dir.exists():
            shutil.rmtree(intermediate_dir)

    def _select_canary_samples(self, sample_states: dict[str, SampleState]) -> list[str]:
        """Select canary sample IDs: samples with high consecutive correct count."""
        candidates = [
            (sample_id, ss.consecutive_correct_count)
            for sample_id, ss in sample_states.items()
            if ss.consecutive_correct_count >= self.config.canary_min_consecutive_correct
        ]
        candidates.sort(key=lambda x: x[1], reverse=True)
        return [sample_id for sample_id, _ in candidates[: self.config.canary_max_count]]

    def _collect_historically_fixed_sample_ids(self, sample_states: dict[str, SampleState]) -> list[str]:
        """Collect sample IDs that were previously fixed (consecutive_correct_count > 0)."""
        return [sample_id for sample_id, ss in sample_states.items() if ss.consecutive_correct_count > 0]

    def _post_apply_regression_check(
        self,
        *,
        round_id: str,
        new_prompt: PromptVersion,
        base_evaluations: list[EvaluationRecord],
        state: OptimizerState,
    ) -> _RegressionCheckResult:
        """Run regression check after patches are applied. Returns regression info."""
        import random

        correct_base_evals = [e for e in base_evaluations if e.overall_status == "correct"]
        if not correct_base_evals:
            return _RegressionCheckResult(regression_count=0, regression_sample_ids=[])

        # Sample a subset of correct base evaluations for regression check
        sample_count = max(1, int(len(correct_base_evals) * self.config.post_apply_regression_sample_ratio))
        sampled_evals = random.Random(round_id).sample(correct_base_evals, min(sample_count, len(correct_base_evals)))

        sample_by_id = {s.id: s for s in state.samples}
        regression_samples = [sample_by_id[e.sample_id] for e in sampled_evals if e.sample_id in sample_by_id]
        if not regression_samples:
            return _RegressionCheckResult(regression_count=0, regression_sample_ids=[])

        run_result = self._prompt_runner().run(
            round_id=round_id,
            run_type=RunType.REGRESSION_CHECK.value,
            prompt=new_prompt,
            samples=regression_samples,
            assets=state.assets,
            ground_truths=state.ground_truths,
            contract=state.extraction_output_schema_contract,
        )

        base_by_sample = {e.sample_id: e for e in correct_base_evals}
        regression_sample_ids: list[str] = []
        for patched_eval in run_result.evaluations:
            base_eval = base_by_sample.get(patched_eval.sample_id)
            if base_eval is None:
                continue
            transition = classify_transition(base_eval, patched_eval)
            if transition == "broken":
                regression_sample_ids.append(patched_eval.sample_id)

        return _RegressionCheckResult(regression_count=len(regression_sample_ids), regression_sample_ids=regression_sample_ids)

    def _apply_contribution_feedback(self, state: OptimizerState, evaluations: list[EvaluationRecord], contribution) -> None:
        for evaluation in evaluations:
            section_scores: list[float] = []
            for attribution in evaluation.used_prompt_sections:
                if isinstance(attribution, dict):
                    section_id = attribution.get("section_id") or attribution.get("target_section")
                else:
                    section_id = str(attribution)
                if section_id and section_id in contribution:
                    section_scores.append(max(0.0, -contribution[section_id].score))
            if not section_scores:
                continue
            sample_state = state.sample_states.setdefault(evaluation.sample_id, SampleState(sample_id=evaluation.sample_id))
            signal = min(1.0, sum(section_scores) / max(1, len(section_scores)) / 5.0)
            sample_state.fragility_score = 0.2 * signal + 0.8 * sample_state.fragility_score

    def _update_sample_state(self, state: OptimizerState, evals: list[EvaluationRecord], round_index: int) -> None:
        for evaluation in evals:
            sample_state = state.sample_states.setdefault(evaluation.sample_id, SampleState(sample_id=evaluation.sample_id))
            error = 0.0 if evaluation.overall_status == "correct" else 1.0
            sample_state.difficulty_ema = 0.2 * error + 0.8 * sample_state.difficulty_ema
            window_expired = (
                sample_state.last_selected_round is None
                or round_index - sample_state.last_selected_round > self.config.dynamic_validation_recent_window_rounds
            )
            if window_expired:
                sample_state.selected_count_recent_window = 0
            sample_state.last_selected_round = round_index
            sample_state.selected_count_recent_window += 1
            if error:
                sample_state.consecutive_wrong_count += 1
                sample_state.consecutive_correct_count = 0
            else:
                sample_state.consecutive_correct_count += 1
                sample_state.consecutive_wrong_count = 0
