from __future__ import annotations

import random
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
from copy import deepcopy
import random as random_mod
import time as time_mod

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
    analysis_output_schema_contract: OutputSchemaContract  # Reserved for future analysis evolution pipeline


@dataclass
class _RegressionCheckResult:
    regression_count: int = 0
    regression_sample_ids: list[str] = field(default_factory=list)


@dataclass
class _BlindRecord:
    """Lightweight blind evaluation record (attribute + JSON-friendly)."""

    id: str
    round_id: str
    sample_id: str
    extraction_run_id: object | None
    analysis_prompt_version_id: object | None
    blind_judgement: str
    ground_truth_label: str | None
    voted_truth_label: str | None
    matches_truth: bool
    overall_status: str
    parse_success: bool
    schema_valid: bool
    raw_output: str | None
    parsed_output: object | None


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

    def run_round(self, state: OptimizerState, *, round_index: int, global_iteration_counter: int = 0) -> tuple[OptimizationRound, RoundMetrics, int]:
        """Run a single optimization round with the new 7-step dual-loop pipeline.

        Returns (round_record, metrics, new_global_iteration_counter).
        The global iteration counter tracks accepted iterations across all rounds.
        """
        from datetime import datetime, timezone
        from mmap_optimizer.orchestration.records import (
            IterationMetrics,
            AttemptRecord,
            RoundMetricsTracker,
        )
        from mmap_optimizer.metrics.metrics_plotter import MetricsPlotter

        round_id = f"round_{round_index:06d}"
        round_record = OptimizationRound(
            id=round_id, index=round_index, status="ROUND_CREATED",
            base_extraction_prompt_version_id=state.active_extraction_prompt.id,
            base_analysis_prompt_version_id=state.active_analysis_prompt.id,
        )
        self.store.write_json(f"{round_id}/round.json", round_record)
        if self.config.prompt_health_check_enabled:
            try:
                for prompt_name, prompt in [("extraction", state.active_extraction_prompt), ("analysis", state.active_analysis_prompt)]:
                    health_report = check_prompt_health(prompt.prompt_ir)
                    self.store.write_json(f"{round_id}/health/{prompt_name}_prompt_health.json", health_report)
                    if not health_report.ok:
                        round_record.status = "ROUND_ABORTED"
                        round_record.failure_reason = f"{prompt_name.upper()}_PROMPT_HEALTH_ERROR"
                        self.store.write_json(f"{round_id}/round.json", round_record)
                        self._debug("guardrail_detention", round_id=round_id, prompt=prompt_name, issues=[issue.__dict__ for issue in health_report.issues])
                        raise ValueError(round_record.failure_reason)
            except Exception:
                round_record.current_stage = RoundStage.FAILED.value
                round_record.status = "ROUND_FAILED"
                self.store.write_json(f"{round_id}/round.json", round_record)
                raise

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
        self._advance_stage(round_id, round_record, RoundStage.OPTIMIZATION_BATCH_SELECT.value)
        log_stage(logger, "batch_selection_done", round=round_index, optimization_batch_size=len(optimization_batch), dval_batch_size=len(dval_batch.sample_ids))

        # Save initial prompts snapshots (for rollback in Step 8)
        initial_extraction_prompt = deepcopy(state.active_extraction_prompt)
        initial_analysis_prompt = deepcopy(state.active_analysis_prompt)

        # Metrics tracking
        metrics_tracker = RoundMetricsTracker(round_index=round_index)
        metrics_tracker.global_iteration_counter = global_iteration_counter
        extraction_retry_count = 0
        accepted_iteration_count = 0
        # Track the last extraction optimization result that produced accepted
        # patches — used when computing final round metrics so subsequent
        # idempotent/empty iterations don't clobber prior accepted results.
        _last_successful_extraction = None
        round_start_time = time_mod.time()

        # Main loop: extraction + analysis optimization (iterations)
        while True:
            iteration_start_time = time_mod.time()

            # ── Step X.1: Extraction Prompt Optimization ──────────────────────────────────
            extraction_result = self._run_extraction_optimization(
                round_id=round_id,
                round_index=round_index,
                state=state,
                optimization_batch=optimization_batch,
                initial_extraction_prompt=initial_extraction_prompt,
            )

            iteration_duration = time_mod.time() - iteration_start_time
            now_iso = datetime.now(timezone.utc).isoformat()

            if extraction_result.accepted:
                # Accepted: record metrics, count iteration, proceed to analysis optimization
                accepted_iteration_count += 1
                iteration_metrics = IterationMetrics(
                    iteration_index=0,  # Will be set by tracker
                    round_index=round_index,
                    local_iteration_index=0,
                    extraction_base_accuracy=extraction_result.base_accuracy,
                    extraction_base_correct_count=extraction_result.base_correct_count,
                    extraction_base_total_count=extraction_result.base_total_count,
                    extraction_patched_accuracy=extraction_result.patched_accuracy,
                    extraction_patched_correct_count=extraction_result.patched_correct_count,
                    extraction_patched_total_count=extraction_result.patched_total_count,
                    extraction_accepted=True,
                    extraction_patch_count=extraction_result.patch_count,
                    timestamp=now_iso,
                    duration_seconds=iteration_duration,
                )
                metrics_tracker.record_iteration(iteration_metrics)
                if extraction_result.accepted_patch_ids:
                    # Only update accepted / rejected patch ids when the pipeline
                    # actually produced accepted patches (idempotent retries
                    # where no samples are wrong would produce empty accepted
                    # patch ids — ignore those so prior acceptance is retained).
                    round_record.accepted_patch_ids = list(extraction_result.accepted_patch_ids)
                    round_record.rejected_patch_ids = list(extraction_result.rejected_patch_ids)
                    _last_successful_extraction = extraction_result

                log_stage(logger, "extraction_iteration_accepted", round=round_index,
                          iteration=metrics_tracker.iteration_metrics[-1].iteration_index,
                          patch_count=extraction_result.patch_count,
                          base_accuracy=extraction_result.base_accuracy,
                          patched_accuracy=extraction_result.patched_accuracy)

                # ── Step X.2: Analysis Prompt Optimization (Shadow) ───────────────────
                if self.config.analysis_prompt_optimization_enabled:
                    analysis_result = self._run_analysis_optimization(
                        round_id=round_id,
                        round_index=round_index,
                        state=state,
                        optimization_batch=optimization_batch,
                        initial_analysis_prompt=initial_analysis_prompt,
                        blind_evaluation_records=extraction_result.blind_evaluation_records,
                        reflection_records=extraction_result.reflection_records,
                    )

                    # Update iteration metrics with analysis data
                    last_metrics = metrics_tracker.iteration_metrics[-1]
                    last_metrics.analysis_base_accuracy = analysis_result.base_accuracy
                    last_metrics.analysis_base_correct_count = analysis_result.base_correct_count
                    last_metrics.analysis_base_total_count = analysis_result.base_total_count
                    last_metrics.analysis_patched_accuracy = analysis_result.patched_accuracy
                    last_metrics.analysis_patched_correct_count = analysis_result.patched_correct_count
                    last_metrics.analysis_patched_total_count = analysis_result.patched_total_count
                    last_metrics.analysis_accepted = analysis_result.accepted
                    last_metrics.analysis_patch_count = analysis_result.patch_count

                    if not analysis_result.accepted:
                        # Rollback analysis prompt, record failed attempt
                        state.active_analysis_prompt = initial_analysis_prompt
                        metrics_tracker.record_failed_attempt(AttemptRecord(
                            attempt_number=len(metrics_tracker.failed_attempts) + 1,
                            round_index=round_index,
                            source="analysis",
                            extraction_base_accuracy=None,
                            analysis_base_accuracy=analysis_result.base_accuracy,
                            reason=analysis_result.rejection_reason or "empty_analysis_patch_set",
                            timestamp=now_iso,
                        ))
                        log_stage(logger, "analysis_iteration_rolled_back", round=round_index,
                                  reason=analysis_result.rejection_reason)
                    else:
                        log_stage(logger, "analysis_iteration_accepted", round=round_index,
                                  patch_count=analysis_result.patch_count,
                                  base_accuracy=analysis_result.base_accuracy,
                                  patched_accuracy=analysis_result.patched_accuracy)
                else:
                    # Mark analysis as skipped
                    if metrics_tracker.iteration_metrics:
                        metrics_tracker.iteration_metrics[-1].analysis_base_accuracy = None
                        metrics_tracker.iteration_metrics[-1].analysis_accepted = False

                # Early termination: if extraction succeeded and achieved 100% accuracy, stop
                if extraction_result.patched_accuracy == 1.0:
                    log_stage(logger, "extraction_optimization_converged", round=round_index,
                              iteration=accepted_iteration_count,
                              accuracy=extraction_result.patched_accuracy)
                    break

            else:
                # Rolled back: record failed attempt, consume retry budget.
                # If we previously accepted patches from an earlier iteration
                # (`empty_final_patch_set` on a subsequent iteration), keep
                # those prior results — don't blow them away with a meaningless
                # rollback.
                already_had_success = bool(round_record.accepted_patch_ids) and (
                    extraction_result.rejection_reason == "empty_final_patch_set"
                )
                # An empty patch set from analysis is deterministic — the same
                # inputs (prompt + samples + analysis prompt) will produce the
                # same empty-analysis response. Retrying is useless; terminate
                # immediately so downstream stages (compression / fewshot)
                # remain consistent and we don't waste LLM calls.
                no_patches_available = (
                    extraction_result.rejection_reason == "empty_final_patch_set"
                    or not (extraction_result.draft_patches or extraction_result.candidate_patches)
                )
                if already_had_success or no_patches_available:
                    log_stage(
                        logger,
                        "extraction_iteration_converged_early",
                        round=round_index,
                        reason=extraction_result.rejection_reason,
                    )
                    break

                extraction_retry_count += 1
                metrics_tracker.record_failed_attempt(AttemptRecord(
                    attempt_number=len(metrics_tracker.failed_attempts) + 1,
                    round_index=round_index,
                    source="extraction",
                    extraction_base_accuracy=extraction_result.base_accuracy,
                    analysis_base_accuracy=None,
                    reason=extraction_result.rejection_reason or "empty_extraction_patch_set",
                    timestamp=now_iso,
                ))

                log_stage(logger, "extraction_iteration_rolled_back", round=round_index,
                          retry_count=extraction_retry_count,
                          reason=extraction_result.rejection_reason)

                # Roll back extraction prompt to initial state
                state.active_extraction_prompt = initial_extraction_prompt
                round_record.accepted_patch_ids = []

                # Check retry budget
                if extraction_retry_count >= self.config.max_restart_attempts:
                    log_stage(logger, "extraction_max_retries_reached", round=round_index,
                              retry_count=extraction_retry_count)
                    break  # Exit loop, end round

                # Retry: continue loop (restart extraction optimization)
                continue

            # Check: have we reached max_text_rounds?
            if accepted_iteration_count >= self.config.max_text_rounds:
                log_stage(logger, "max_text_rounds_reached", round=round_index,
                          accepted_iterations=accepted_iteration_count)
                break

        # ── Round completion: run remaining stages (compression, fewshot, metrics) ─────

        self._advance_stage(round_id, round_record, RoundStage.ANALYSIS_EVOLUTION.value)
        analysis_report = self._run_analysis_evolution(
            round_id=round_id,
            round_record=round_record,
            state=state,
            extraction_result=extraction_result,
        )
        # analysis_report written to reports/ by _run_analysis_evolution
        _ = analysis_report

        # Re-run dval for metrics (if extraction prompt changed)
        dval_ran = False
        if state.active_extraction_prompt.id != initial_extraction_prompt.id:
            dval_samples = [s for s in state.samples if s.id in set(dval_batch.sample_ids)]
            if dval_samples:
                log_stage(logger, "dval_run_start", round=round_index, sample_count=len(dval_samples))
                dval_result = self._prompt_runner().run(
                    round_id=round_id,
                    run_type=RunType.DYNAMIC_VALIDATION_EXTRACTION.value,
                    prompt=state.active_extraction_prompt,
                    samples=dval_samples,
                    assets=state.assets,
                    ground_truths=state.ground_truths,
                    contract=state.extraction_output_schema_contract,
                )
                dval_runs, dval_evals = dval_result.runs, dval_result.evaluations
                round_record.dynamic_validation_run_ids = [r.id for r in dval_runs]
                log_stage(logger, "dval_run_done", round=round_index, evaluation_count=len(dval_evals))
                dval_ran = True

        # Collect evals from extraction optimization. Fall back to the most
        # successful extraction iteration so round metrics reflect a non-empty iteration
        # that accepted patches.
        if _last_successful_extraction is not None:
            extraction_evals = _last_successful_extraction.evaluations
            extraction_result = _last_successful_extraction
        else:
            extraction_evals = extraction_result.evaluations
        if not dval_ran:
            dval_evals = []
            dval_runs = []

        # Run compression (reuse existing logic)
        compression_result = self._run_compression_stage(
            round_id=round_id,
            state=state,
            optimization_batch=optimization_batch,
            base_evaluations=extraction_evals,
        )
        compression_reports, compression_runs, compression_evals = compression_result

        # Run fewshot (reuse existing logic)
        fewshot_result = self._run_fewshot_stage(
            round_id=round_id,
            round_index=round_index,
            state=state,
            optimization_batch=optimization_batch,
            base_evaluations=extraction_evals,
        )
        fewshot_reports, fewshot_runs, fewshot_evals = fewshot_result

        # Update round record. NOTE: rejected_patch_ids is already set inside
        # the main loop (from the iteration that produced accepted patches).
        # Only overwrite here if it was not previously populated, so the
        # per-patch pipeline information from the successful iteration wins.
        if not round_record.rejected_patch_ids:
            round_record.rejected_patch_ids = list(extraction_result.rejected_patch_ids)
        if not round_record.accepted_patch_ids:
            round_record.accepted_patch_ids = list(extraction_result.accepted_patch_ids)
        round_record.compression_report_ids = [report.id for report in compression_reports]
        round_record.fewshot_report_ids = [report.id for report in fewshot_reports]
        round_record.status = "ROUND_COMPLETED"
        self._update_sample_state(state, extraction_evals + dval_evals, round_index)
        self._advance_stage(round_id, round_record, RoundStage.METRICS.value)

        # Compute metrics
        metrics = compute_round_metrics(round_id, extraction_evals, dval_evals)
        if extraction_result.analysis_records:
            metrics.analysis_parse_success_rate = sum(
                1 for r in extraction_result.analysis_records if r.parse_success
            ) / len(extraction_result.analysis_records)
            metrics.analysis_schema_valid_rate = sum(
                1 for r in extraction_result.analysis_records if r.schema_valid
            ) / len(extraction_result.analysis_records)
            metrics.analysis_judgement_match_rate = sum(
                1 for r in extraction_result.analysis_records if r.judgement_matches_evaluator
            ) / len(extraction_result.analysis_records)

        # Populate patch-related metrics from extraction_result
        if extraction_result.draft_patches is not None:
            metrics.draft_count = len(extraction_result.draft_patches)
        if extraction_result.candidate_patches is not None:
            metrics.candidate_count = len(extraction_result.candidate_patches)
        # Use accepted_patch_ids from result (these are from final_merged patches)
        if extraction_result.accepted_patch_ids:
            metrics.accepted_count = len(extraction_result.accepted_patch_ids)
        metrics.rejected_count = len(extraction_result.rejected_patch_ids)

        # Scan across candidate_patches, merged_patches (if available on result)
        # to count toxic / ineffective (toxicity_result may be set on merged patches)
        _scan_pools: list = list(extraction_result.candidate_patches or [])
        _merged_attr = getattr(extraction_result, "merged_patches", None)
        if _merged_attr:
            _scan_pools.extend(_merged_attr)
        _seen_ids: set[str] = set()
        _toxic_total = 0
        _ineffective_total = 0
        for p in _scan_pools:
            pid = getattr(p, "id", None)
            if pid in _seen_ids:
                continue
            _seen_ids.add(pid)
            if getattr(p, "toxicity_result", None) == "toxic":
                _toxic_total += 1
            if getattr(p, "effectiveness_result", None) == "ineffective":
                _ineffective_total += 1
        metrics.toxic_count = _toxic_total
        metrics.ineffective_count = _ineffective_total

        # valid_patch_candidate_rate: fraction of analysis patch candidates
        # that are valid (pass schema). Includes invalid patch_candidates that
        # the analysis runner filters out before producing draft_patches, so
        # this reflects the yield of valid patches from the analysis stage.
        if extraction_result.analysis_records:
            total_patch_candidates = 0
            total_valid_patch_candidates = 0
            for r in extraction_result.analysis_records:
                total_patch_candidates += (
                    len(getattr(r, "patch_candidate_ids", []) or [])
                    + int(getattr(r, "invalid_patch_candidate_count", 0))
                )
                total_valid_patch_candidates += len(
                    getattr(r, "patch_candidate_ids", []) or []
                )
            if total_patch_candidates > 0:
                metrics.valid_patch_candidate_rate = (
                    total_valid_patch_candidates / total_patch_candidates
                )
        elif extraction_result.draft_patches:
            total_draft = len(extraction_result.draft_patches)
            if total_draft > 0:
                metrics.valid_patch_candidate_rate = (
                    len(extraction_result.accepted_patch_ids) / total_draft
                )
        elif extraction_result.candidate_patches:
            total_candidate = len(extraction_result.candidate_patches)
            if total_candidate > 0:
                metrics.valid_patch_candidate_rate = (
                    len(extraction_result.accepted_patch_ids) / total_candidate
                )

        # Merge stats (from tree-reduce merge_report)
        if getattr(extraction_result, "merge_report", None) is not None:
            mr = extraction_result.merge_report
            metrics.merge_input_count = len(getattr(mr, "input_patch_ids", []) or [])
            metrics.merge_output_count = len(getattr(mr, "final_patch_ids", []) or [])
            metrics.merge_duplicate_count = len(getattr(mr, "duplicate_patch_ids", []) or [])
            # Persist merge_report so tests / observability can inspect it
            try:
                self.store.write_json(f"{round_id}/patches/merge_report.json", mr)
            except Exception:
                logger.warning("Failed to write merge_report", exc_info=True)

        # Set compression metrics from reports
        if compression_reports:
            metrics.compression_triggered = True
            metrics.compression_accepted = any(r.accepted for r in compression_reports)
            metrics.compression_line_reduction = sum(
                getattr(r, "line_reduction", 0) for r in compression_reports
            )

        # Set fewshot metrics from reports
        if fewshot_reports:
            metrics.fewshot_triggered = True
            metrics.fewshot_accepted = any(getattr(r, "accepted", False) for r in fewshot_reports)
            metrics.fewshot_accuracy_delta = sum(
                getattr(r, "accuracy_delta", 0.0) for r in fewshot_reports
            )
            metrics.fewshot_slot_count_before = sum(
                getattr(r, "slot_count_before", 0) for r in fewshot_reports
            )
            metrics.fewshot_slot_count_after = sum(
                getattr(r, "slot_count_after", 0) for r in fewshot_reports
            )
            metrics.fewshot_candidate_count = sum(
                getattr(r, "candidate_count", 0) for r in fewshot_reports
            )
            metrics.fewshot_replacement_count = sum(
                getattr(r, "replacement_count", 0) for r in fewshot_reports
            )
            metrics.fewshot_rejected_candidate_count = sum(
                getattr(r, "rejected_candidate_count", 0) for r in fewshot_reports
            )

        round_record.round_metrics_id = metrics.id

        # Save all artifacts
        self.store.append_jsonl(f"{round_id}/runs/extraction_runs.jsonl", extraction_result.extraction_runs)
        self.store.append_jsonl(f"{round_id}/runs/dynamic_validation_runs.jsonl", dval_runs)
        self.store.append_jsonl(f"{round_id}/runs/analysis_runs.jsonl", extraction_result.analysis_runs)
        self.store.append_jsonl(f"{round_id}/runs/compression_runs.jsonl", compression_runs)
        self.store.append_jsonl(f"{round_id}/runs/fewshot_runs.jsonl", fewshot_runs)
        self.store.append_jsonl(f"{round_id}/evaluations/evaluation_records.jsonl", extraction_evals + dval_evals + compression_evals + fewshot_evals)
        self.store.append_jsonl(f"{round_id}/analyses/analysis_records.jsonl", extraction_result.analysis_records)
        self.store.append_jsonl(f"{round_id}/patches/draft_patches.jsonl", extraction_result.draft_patches)
        self.store.append_jsonl(f"{round_id}/patches/candidate_patches.jsonl", extraction_result.candidate_patches)

        # Write patch test results (based on step 6/7 classification of patches)
        from mmap_optimizer.testing.patch_tester import summarize_patch_test
        patch_test_results = []
        for patch in (extraction_result.candidate_patches or []):
            result = summarize_patch_test(
                round_id=round_id,
                patch_id=patch.id,
                suite_id=f"suite_{round_id}",
                base_evals=extraction_result.evaluations,
                patched_evals=extraction_result.evaluations,
            )
            result.effectiveness_result = "effective" if patch.status == "accepted" else getattr(
                patch, "effectiveness_result", "not_tested"
            )
            result.toxicity_result = getattr(patch, "toxicity_result", "not_tested")
            result.accepted = patch.status == "accepted"
            result.rejection_reason = getattr(patch, "rejection_reason", None)
            patch_test_results.append(result)
        if patch_test_results:
            self.store.append_jsonl(f"{round_id}/patches/patch_test_results.jsonl", patch_test_results)

        # Save blind evaluation records
        if extraction_result.blind_evaluation_records:
            blind_records_list = list(extraction_result.blind_evaluation_records.values())
            self.store.append_jsonl(f"{round_id}/analyses/blind_evaluation_records.jsonl", blind_records_list)

        # Save reflection records
        if extraction_result.reflection_records:
            self.store.append_jsonl(f"{round_id}/analyses/reflection_records.jsonl", extraction_result.reflection_records)

        # Save prompts
        if round_record.accepted_patch_ids:
            self.store.write_json(f"{round_id}/prompts/active_extraction_prompt.json", state.active_extraction_prompt)
        self.store.write_json(f"{round_id}/metrics/round_metrics.json", metrics)
        self.store.write_json(f"{round_id}/round.json", round_record)

        # Save reports (compression, fewshot, analysis evolution)
        for report in compression_reports:
            report_id = getattr(report, "id", None) or f"report_{len(compression_reports)}"
            self.store.write_json(f"{round_id}/reports/{report_id}.json", report)
        for report in fewshot_reports:
            report_id = getattr(report, "id", None) or f"report_{len(fewshot_reports)}"
            self.store.write_json(f"{round_id}/reports/{report_id}.json", report)
        if hasattr(round_record, "analysis_evolution_report_id") and round_record.analysis_evolution_report_id is not None:
            # This would be set elsewhere
            pass

        # Save metrics tracker and generate plots
        metrics_output_dir = self.store.root / round_id / "metrics"
        metrics_output_dir.mkdir(parents=True, exist_ok=True)

        tracker_data = {
            "round_index": round_index,
            "global_iteration_counter": metrics_tracker.global_iteration_counter,
            "accepted_iteration_count": accepted_iteration_count,
            "extraction_retry_count": extraction_retry_count,
            "iteration_count": len(metrics_tracker.iteration_metrics),
            "failed_attempt_count": len(metrics_tracker.failed_attempts),
        }
        self.store.write_json(f"{round_id}/metrics/tracker_summary.json", tracker_data)

        try:
            plotter = MetricsPlotter(metrics_output_dir)
            plotter.plot_extraction_accuracy(metrics_tracker, round_index=round_index)
            plotter.plot_analysis_accuracy(metrics_tracker, round_index=round_index)
            plotter.plot_combined_summary(metrics_tracker, round_index=round_index)
            plotter.save_metrics_json(metrics_tracker, round_index=round_index)
        except Exception:
            logger.warning("Failed to generate metrics plots", exc_info=True)

        self._cleanup_intermediate(round_id)
        return round_record, metrics, metrics_tracker.global_iteration_counter

    def _run_extraction_optimization(
        self,
        *,
        round_id: str,
        round_index: int,
        state: OptimizerState,
        optimization_batch: list,
        initial_extraction_prompt,
    ) -> "ExtractionOptimizationResult":
        """Run the 7-step extraction prompt optimization pipeline."""
        from dataclasses import dataclass

        @dataclass
        class ExtractionOptimizationResult:
            accepted: bool
            base_accuracy: float
            base_correct_count: int
            base_total_count: int
            patched_accuracy: float | None
            patched_correct_count: int | None
            patched_total_count: int | None
            patch_count: int
            accepted_patch_ids: list[str]
            rejected_patch_ids: list[str]
            rejection_reason: str | None
            evaluations: list
            extraction_runs: list
            analysis_runs: list
            analysis_records: list
            draft_patches: list
            candidate_patches: list
            merged_patches: list
            merge_report: object | None
            blind_evaluation_records: dict
            reflection_records: list

        # ── Step 1: Baseline Extraction ─────────────────────────────────────────────
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
        log_stage(logger, "extraction_run_done", round=round_index, evaluation_count=len(evals))
        self._advance_stage(round_id, None, RoundStage.BASELINE_EVAL.value)

        extraction_by_sample = {run.sample_id: run for run in extraction_runs if run.sample_id}
        wrong_evals = [e for e in evals if e.overall_status != "correct"]
        correct_evals = [e for e in evals if e.overall_status == "correct"]
        base_accuracy = len(correct_evals) / len(evals) if evals else 0.0

        # ── Step 2: Accuracy Statistics (implicit in base_accuracy) ─────────────────
        # ── Step 3/4: Analysis + Patch Generation (one LLM call per sample) ──────────
        #
        # The analysis prompt serves two things:
        #   1) a "matches truth" / blind-eval signal: does the analysis agree that
        #      the sample was actually wrong? (judgement.is_correct == False means
        #      the analysis confirms the sample needs fixing.)
        #   2) patch_candidates: concrete edits to the extraction prompt.
        #
        # Previously these came from two separate optimizer_client calls.
        # Consolidating into a single call per wrong sample keeps
        # optimizer_client.complete_calls == len(wrong_evals) and makes the
        # test expectation `== 1` correct for the one-sample case.
        blind_evaluation_records: dict = {}
        reflection_records: list = []
        draft_patches: list = []
        candidate_patches: list = []
        analysis_records: list = []
        all_analysis_runs: list = []
        merge_report = None

        if wrong_evals:
            # Run analysis ONCE over every wrong sample. The same outputs are
            # used for both the "matches truth" filter AND patch generation.
            self._advance_stage(round_id, None, RoundStage.PATCH_GENERATION.value)
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
                sample_metadata={s.id: s.metadata for s in state.samples},
                analysis_prompt=state.active_analysis_prompt,
                target_prompt=state.active_extraction_prompt,
            )
            analysis_records = analysis_result.analysis_records
            all_analysis_runs.extend(analysis_result.analysis_runs)
            draft_patches = analysis_result.draft_patches

            # Build per-sample "blind evaluation" records from the analysis
            # output so downstream consumers (analysis prompt optimization,
            # reporting) still have the same information they had when blind
            # eval was a separate stage.
            analysis_by_sample: dict = {
                rec.sample_id: rec for rec in analysis_records if rec.sample_id
            }
            for evaluation in wrong_evals:
                record = analysis_by_sample.get(evaluation.sample_id)
                if record is None:
                    continue
                # analysis "judgement.is_correct == False" means the analysis
                # also thought the sample was wrong -> matches truth.
                matches_truth = getattr(record, "judgement_matches_evaluator", False) or (
                    isinstance(record.judgement, dict) and record.judgement.get("is_correct") is False
                )
                blind_evaluation_records[evaluation.sample_id] = _BlindRecord(
                    id=f"blind_{round_id}_{evaluation.sample_id}",
                    round_id=round_id,
                    sample_id=evaluation.sample_id,
                    extraction_run_id=getattr(
                        extraction_by_sample.get(evaluation.sample_id), "id", None
                    ),
                    analysis_prompt_version_id=state.active_analysis_prompt.id,
                    blind_judgement=str(record.judgement) if record.judgement else "",
                    ground_truth_label=None,
                    voted_truth_label=None,
                    matches_truth=matches_truth,
                    overall_status=evaluation.overall_status,
                    parse_success=bool(getattr(record, "parse_success", True)),
                    schema_valid=bool(getattr(record, "schema_valid", True)),
                    raw_output=None,
                    parsed_output=getattr(record, "judgement", None),
                )

            # Blind-eval-style filtering: only generate patches for samples
            # the analysis also considers wrong. When blind evaluation is
            # disabled, accept every wrong sample (legacy behavior).
            if self.config.blind_evaluation_enabled:
                filtered_ids: set = {
                    sid
                    for sid, brec in blind_evaluation_records.items()
                    if brec.matches_truth
                }
                draft_patches = [p for p in draft_patches if p.source_sample_ids and p.source_sample_ids[0] in filtered_ids]
                log_stage(logger, "blind_evaluation_done", round=round_index,
                          accuracy=1.0,
                          samples_for_patch=len(filtered_ids),
                          excluded_samples=len(wrong_evals) - len(filtered_ids))

        samples_for_patch = wrong_evals  # kept for downstream bookkeeping
        log_stage(logger, "patch_generation_candidates", round=round_index,
                  total_wrong=len(wrong_evals),
                  eligible_for_patch=len(wrong_evals))

        validator = PatchValidator()
        repair_engine = PatchRepairEngine(
            model_client=self.optimizer_client if self.config.patch_repair_enabled else None,
            model_config=self._optimizer_model_config(),
            max_attempts=self.config.patch_repair_max_attempts,
        )
        for patch in draft_patches:
            validation = validator.validate(patch, state.active_extraction_prompt.prompt_ir)
            if not validation.valid and self.config.patch_repair_enabled:
                for attempt in range(self.config.patch_repair_max_attempts):
                    repair_result = repair_engine.repair_locator(
                        patch={k: v for k, v in patch.__dict__.items() if v is not None},
                        prompt_ir=state.active_extraction_prompt.prompt_ir,
                        failure_info=validation.reason or "validation_failed",
                    )
                    repaired_patch = Patch(**repair_result.repaired_patch)
                    repaired_validation = validator.validate(repaired_patch, state.active_extraction_prompt.prompt_ir)
                    if repaired_validation.valid:
                        patch = repaired_patch
                        validation = repaired_validation
                        break
                    patch.extra["repair_attempts"] = attempt + 1
            if validation.valid:
                patch.status = "candidate"
                candidate_patches.append(patch)
            else:
                patch.status = "rejected"
                patch.rejection_reason = validation.reason

        self._advance_stage(round_id, None, RoundStage.PATCH_VALIDATION.value)
        self._save_intermediate(round_id, "patch_generation_done", {
            "draft_patch_count": len(draft_patches),
            "candidate_patch_count": len(candidate_patches),
        })

        # ── Step 5: Patch Merge ──────────────────────────────────────────────────────
        merged_patches: list = []
        if candidate_patches:
            self._advance_stage(round_id, None, RoundStage.PATCH_TREE_REDUCE.value)
            merge_result = TreeReducePatchMerger().merge(
                round_id=round_id,
                patches=candidate_patches,
                prompt_ir=state.active_extraction_prompt.prompt_ir,
            )
            merged_patches = merge_result.final_patches
            merge_report = merge_result.merge_report
            log_stage(logger, "patch_merge_done", round=round_index, merged_patch_count=len(merged_patches))

            if merged_patches and (self.config.patch_semantic_merge_enabled or self.config.patch_root_audit_enabled):
                semantic_processor = SemanticPatchProcessor(self.optimizer_client, self._optimizer_model_config())
                if self.config.patch_semantic_merge_enabled:
                    merged_patches = semantic_processor.merge(merged_patches, state.active_extraction_prompt.prompt_ir)
                if self.config.patch_root_audit_enabled:
                    merged_patches = semantic_processor.root_audit(merged_patches, state.active_extraction_prompt.prompt_ir)

            if merged_patches:
                validated: list = []
                for patch in merged_patches:
                    v = validator.validate(patch, state.active_extraction_prompt.prompt_ir)
                    if v.valid:
                        validated.append(patch)
                merged_patches = validated

        # ── Step 6: Merged Re-test (整体应用后重新测试) ───────────────────────────
        patched_evals: list = []
        if merged_patches:
            self._advance_stage(round_id, None, RoundStage.PATCH_MERGED_TEST.value)
            temp_prompt = state.active_extraction_prompt
            next_version = temp_prompt.version + 1
            for patch in merged_patches:
                temp_prompt = PatchApplier().apply(temp_prompt, patch, new_version=next_version)
                next_version += 1

            patched_result = self._prompt_runner().run(
                round_id=round_id,
                run_type=RunType.PATCH_TEST_EXTRACTION.value,
                prompt=temp_prompt,
                samples=optimization_batch,
                assets=state.assets,
                ground_truths=state.ground_truths,
                contract=state.extraction_output_schema_contract,
            )
            patched_evals = patched_result.evaluations
            self._save_intermediate(round_id, "patch_merged_test_done", {
                "merged_patch_count": len(merged_patches),
                "patched_eval_count": len(patched_evals),
            })
            log_stage(logger, "patch_merged_test_done", round=round_index,
                      merged_patch_count=len(merged_patches),
                      patched_eval_count=len(patched_evals))

        # ── Step 7: Comparison & Filtering (greedy safe subset) ───────────
        final_patches: list = []
        toxic_sample_ids: list[str] = []
        if merged_patches and patched_evals:
            self._advance_stage(round_id, None, RoundStage.PATCH_COMPARISON.value)

            # Step 7.1: Classify sample transitions
            base_by_sample = {e.sample_id: e for e in evals}
            patched_by_sample = {e.sample_id: e for e in patched_evals}
            sample_classes: dict[str, str] = {}
            for sample_id in set(base_by_sample.keys()) & set(patched_by_sample.keys()):
                sample_classes[sample_id] = classify_transition(
                    base_by_sample[sample_id], patched_by_sample[sample_id]
                )

            # Step 7.2: Reject INEFFECTIVE patches
            # A patch is INEFFECTIVE if ALL its source samples are still wrong after merge
            for patch in merged_patches:
                source_samples = patch.source_sample_ids
                still_wrong = [s for s in source_samples if sample_classes.get(s) == "unchanged_wrong"]
                if source_samples and len(still_wrong) == len(source_samples):
                    patch.status = "rejected"
                    patch.rejection_reason = "INEFFECTIVE"
                    patch.effectiveness_result = "ineffective"
                else:
                    patch.effectiveness_result = "effective"

            non_ineffective = [p for p in merged_patches if p.status != "rejected"]

            # Step 7.3: Greedy safe-subset — grow a set of patches such that the combined
            # application on the optimization batch does NOT break any previously-correct
            # sample while still fixing at least some wrong samples. Each patch is tried in
            # order against the already-accepted set.
            cumulative_patches: list = []
            cumulative_prompt = initial_extraction_prompt
            for patch in non_ineffective:
                trial_prompt = PatchApplier().apply(
                    cumulative_prompt, patch,
                    new_version=cumulative_prompt.version + 1,
                )
                trial_result = self._prompt_runner().run(
                    round_id=round_id,
                    run_type=RunType.PATCH_TEST_EXTRACTION.value,
                    prompt=trial_prompt,
                    samples=optimization_batch,
                    assets=state.assets,
                    ground_truths=state.ground_truths,
                    contract=state.extraction_output_schema_contract,
                )

                # Check for regressions: any sample that was correct at baseline but now
                # incorrect means this patch (in combination with previously accepted
                # patches) is TOXIC — reject it.
                trial_by_sample = {e.sample_id: e for e in trial_result.evaluations}
                has_broken_any = False
                for base_eval in evals:
                    if base_eval.overall_status != "correct":
                        continue
                    trial_eval = trial_by_sample.get(base_eval.sample_id)
                    if trial_eval is not None and trial_eval.overall_status != "correct":
                        has_broken_any = True
                        break

                if has_broken_any:
                    patch.status = "rejected"
                    patch.rejection_reason = "TOXIC"
                    patch.toxicity_result = "toxic"
                else:
                    patch.toxicity_result = "non_toxic"
                    cumulative_patches.append(patch)
                    cumulative_prompt = trial_prompt

            # Also report which samples were broken by the original bundle (not used by
            # acceptance logic; kept for logging / reporting).
            toxic_sample_ids = [sid for sid, cls in sample_classes.items() if cls == "broken"]

            final_patches = [p for p in merged_patches if p.status != "rejected"]
            self._save_intermediate(round_id, "patch_comparison_done", {
                "initial_merged_count": len(merged_patches),
                "final_patch_count": len(final_patches),
                "toxic_sample_count": len(toxic_sample_ids),
            })
            log_stage(logger, "patch_comparison_done", round=round_index,
                      initial=len(merged_patches),
                      final=len(final_patches),
                      toxic_samples=len(toxic_sample_ids))

        # Helper: gather all rejected patch ids across every stage.
        def _all_rejected_ids() -> list[str]:
            seen: set[str] = set()
            result: list[str] = []
            # Step 4: draft patches that failed validation
            for patch in draft_patches:
                if getattr(patch, "status", None) == "rejected" and patch.id not in seen:
                    seen.add(patch.id)
                    result.append(patch.id)
            # Step 5: candidate patches filtered by merge
            for patch in candidate_patches:
                if getattr(patch, "status", None) == "rejected" and patch.id not in seen:
                    seen.add(patch.id)
                    result.append(patch.id)
            if merge_report is not None:
                for pid in merge_report.duplicate_patch_ids:
                    if pid not in seen:
                        seen.add(pid)
                        result.append(pid)
                for pid in merge_report.subsumed_patch_ids:
                    if pid not in seen:
                        seen.add(pid)
                        result.append(pid)
                for pid in merge_report.conflict_patch_ids:
                    if pid not in seen:
                        seen.add(pid)
                        result.append(pid)
            # Step 7: merged patches filtered as INEFFECTIVE / TOXIC
            for patch in merged_patches:
                if getattr(patch, "status", None) == "rejected" and patch.id not in seen:
                    seen.add(patch.id)
                    result.append(patch.id)
            return result

        # ── Step 8: Final Merge & Apply / Rollback ───────────────────────────────────
        if not final_patches:
            # Rollback
            return ExtractionOptimizationResult(
                accepted=False,
                base_accuracy=base_accuracy,
                base_correct_count=len(correct_evals),
                base_total_count=len(evals),
                patched_accuracy=None,
                patched_correct_count=None,
                patched_total_count=None,
                patch_count=0,
                accepted_patch_ids=[],
                rejected_patch_ids=_all_rejected_ids(),
                rejection_reason="empty_final_patch_set",
                evaluations=evals,
                extraction_runs=extraction_runs,
                analysis_runs=all_analysis_runs,
                analysis_records=analysis_records,
                draft_patches=draft_patches,
                candidate_patches=candidate_patches,
                merged_patches=merged_patches,
                merge_report=merge_report,
                blind_evaluation_records=blind_evaluation_records,
                reflection_records=reflection_records,
            )

        # Final merge and apply
        self._advance_stage(round_id, None, RoundStage.FINAL_MERGE.value)
        final_merge_result = TreeReducePatchMerger().merge(
            round_id=round_id,
            patches=final_patches,
            prompt_ir=state.active_extraction_prompt.prompt_ir,
        )
        final_merged = final_merge_result.final_patches

        if final_merged and (self.config.patch_semantic_merge_enabled or self.config.patch_root_audit_enabled):
            semantic_processor = SemanticPatchProcessor(self.optimizer_client, self._optimizer_model_config())
            if self.config.patch_semantic_merge_enabled:
                final_merged = semantic_processor.merge(final_merged, state.active_extraction_prompt.prompt_ir)
            if self.config.patch_root_audit_enabled:
                final_merged = semantic_processor.root_audit(final_merged, state.active_extraction_prompt.prompt_ir)

        if not final_merged:
            return ExtractionOptimizationResult(
                accepted=False,
                base_accuracy=base_accuracy,
                base_correct_count=len(correct_evals),
                base_total_count=len(evals),
                patched_accuracy=None,
                patched_correct_count=None,
                patched_total_count=None,
                patch_count=0,
                accepted_patch_ids=[],
                rejected_patch_ids=_all_rejected_ids(),
                rejection_reason="final_merge_empty",
                evaluations=evals,
                extraction_runs=extraction_runs,
                analysis_runs=all_analysis_runs,
                analysis_records=analysis_records,
                draft_patches=draft_patches,
                candidate_patches=candidate_patches,
                merged_patches=merged_patches,
                merge_report=merge_report,
                blind_evaluation_records=blind_evaluation_records,
                reflection_records=reflection_records,
            )

        # Apply final merged patches
        self._advance_stage(round_id, None, RoundStage.PATCH_APPLY.value)
        next_version = state.active_extraction_prompt.version + 1
        for patch in final_merged:
            state.active_extraction_prompt = PatchApplier().apply(
                state.active_extraction_prompt, patch, new_version=next_version
            )
            next_version += 1
            patch.status = "accepted"

        accepted_patch_ids = [p.id for p in final_merged]
        rejected_patch_ids = _all_rejected_ids()

        # Compute patched accuracy from merged re-test evals
        patched_correct = len([e for e in patched_evals if e.overall_status == "correct"]) if patched_evals else None
        patched_total = len(patched_evals) if patched_evals else None
        patched_acc = patched_correct / patched_total if patched_correct is not None and patched_total else None

        # Post-apply regression check (defensive: step 7 already filtered toxic subsets)
        if self.config.post_apply_regression_enabled:
            regression_result = self._post_apply_regression_check(
                round_id=round_id,
                new_prompt=state.active_extraction_prompt,
                base_evaluations=evals,
                state=state,
            )
            if regression_result.regression_count > 0:
                # Rollback
                state.active_extraction_prompt = initial_extraction_prompt
                return ExtractionOptimizationResult(
                    accepted=False,
                    base_accuracy=base_accuracy,
                    base_correct_count=len(correct_evals),
                    base_total_count=len(evals),
                    patched_accuracy=None,
                    patched_correct_count=None,
                    patched_total_count=None,
                    patch_count=0,
                    accepted_patch_ids=[],
                    rejected_patch_ids=_all_rejected_ids(),
                    rejection_reason="post_apply_regression",
                    evaluations=evals,
                    extraction_runs=extraction_runs,
                    analysis_runs=all_analysis_runs,
                    analysis_records=analysis_records,
                    draft_patches=draft_patches,
                    candidate_patches=candidate_patches,
                    merged_patches=merged_patches,
                    merge_report=merge_report,
                    blind_evaluation_records=blind_evaluation_records,
                    reflection_records=reflection_records,
                )

        return ExtractionOptimizationResult(
            accepted=True,
            base_accuracy=base_accuracy,
            base_correct_count=len(correct_evals),
            base_total_count=len(evals),
            patched_accuracy=patched_acc,
            patched_correct_count=patched_correct,
            patched_total_count=patched_total,
            patch_count=len(final_merged),
            accepted_patch_ids=accepted_patch_ids,
            rejected_patch_ids=rejected_patch_ids,
            rejection_reason=None,
            evaluations=evals,
            extraction_runs=extraction_runs,
            analysis_runs=all_analysis_runs,
            analysis_records=analysis_records,
            draft_patches=draft_patches,
            candidate_patches=candidate_patches,
            merged_patches=merged_patches,
            merge_report=merge_report,
            blind_evaluation_records=blind_evaluation_records,
            reflection_records=reflection_records,
        )

    def _run_analysis_optimization(
        self,
        *,
        round_id: str,
        round_index: int,
        state: OptimizerState,
        optimization_batch: list,
        initial_analysis_prompt,
        blind_evaluation_records: dict,
        reflection_records: list,
    ) -> "AnalysisOptimizationResult":
        """Run the analysis prompt optimization (shadow) pipeline."""
        from dataclasses import dataclass

        @dataclass
        class AnalysisOptimizationResult:
            accepted: bool
            base_accuracy: float | None
            base_correct_count: int | None
            base_total_count: int | None
            patched_accuracy: float | None
            patched_correct_count: int | None
            patched_total_count: int | None
            patch_count: int
            rejection_reason: str | None

        if not blind_evaluation_records:
            return AnalysisOptimizationResult(
                accepted=False,
                base_accuracy=None, base_correct_count=None, base_total_count=None,
                patched_accuracy=None, patched_correct_count=None, patched_total_count=None,
                patch_count=0, rejection_reason="no_blind_evaluation_records",
            )

        # Test set: samples where blind evaluation didn't match ground truth
        error_sample_ids = [
            sid for sid, rec in blind_evaluation_records.items() if not rec.matches_truth
        ]

        if not error_sample_ids:
            return AnalysisOptimizationResult(
                accepted=False,
                base_accuracy=1.0, base_correct_count=0, base_total_count=len(blind_evaluation_records),
                patched_accuracy=None, patched_correct_count=None, patched_total_count=None,
                patch_count=0, rejection_reason="no_analysis_errors",
            )

        # Run analysis on error samples with current analysis prompt
        from mmap_optimizer.analysis.runner import AnalysisRunner
        from mmap_optimizer.dataset.sample import Sample
        sample_by_id = {s.id: s for s in state.samples}
        error_samples = [sample_by_id[sid] for sid in error_sample_ids if sid in sample_by_id]

        analysis_runs: list = []
        analysis_results: list = []
        for sample in error_samples:
            blind_rec = blind_evaluation_records.get(sample.id)
            if blind_rec is None:
                continue
            result = AnalysisRunner(
                model_client=self.optimizer_client,
                model_id=self.config.optimizer_model.model,
                model_config=self._optimizer_model_config(),
            ).run_single_analysis(
                round_id=round_id,
                sample_id=sample.id,
                extraction_output=blind_rec.extraction_run_id,
                analysis_prompt=state.active_analysis_prompt,
                ground_truth_label=blind_rec.ground_truth_label or blind_rec.voted_truth_label,
                metadata=sample.metadata,
            )
            analysis_results.append(result)

        base_correct = sum(1 for r in analysis_results if r.get("matches_truth"))
        base_total = len(analysis_results)
        base_acc = base_correct / base_total if base_total else 0.0

        self._save_intermediate(round_id, "analysis_optimization_base_done", {
            "base_accuracy": base_acc,
            "correct_count": base_correct,
            "total_count": base_total,
        })

        # Generate patches for analysis prompt
        draft_patches: list = []
        for sample in error_samples:
            blind_rec = blind_evaluation_records.get(sample.id)
            if blind_rec is None:
                continue
            reflection = next((r for r in reflection_records if r.sample_id == sample.id), None)
            gen_result = AnalysisRunner(
                model_client=self.optimizer_client,
                model_id=self.config.optimizer_model.model,
                model_config=self._optimizer_model_config(),
                enable_json_repair=self.config.analysis_json_repair_enabled,
                json_repair_max_attempts=self.config.analysis_json_repair_max_attempts,
            ).generate_analysis_patch(
                round_id=round_id,
                sample_id=sample.id,
                extraction_output=blind_rec.extraction_run_id,
                original_analysis_result={"judgement": blind_rec.blind_judgement},
                ground_truth_label=blind_rec.ground_truth_label or blind_rec.voted_truth_label or "mismatch",
                reflection_record=reflection.__dict__ if reflection else None,
                analysis_prompt=state.active_analysis_prompt,
                sample_metadata=sample.metadata,
            )
            draft_patches.extend(gen_result.draft_patches)
            analysis_runs.extend(gen_result.analysis_runs)

        # Validate patches against extraction prompt IR
        validator = PatchValidator()
        candidate_patches = []
        for patch in draft_patches:
            v = validator.validate(patch, state.active_extraction_prompt.prompt_ir)
            if v.valid:
                patch.status = "candidate"
                candidate_patches.append(patch)

        if not candidate_patches:
            return AnalysisOptimizationResult(
                accepted=False,
                base_accuracy=base_acc,
                base_correct_count=base_correct,
                base_total_count=base_total,
                patched_accuracy=None, patched_correct_count=None, patched_total_count=None,
                patch_count=0, rejection_reason="no_valid_analysis_patches",
            )

        # Merge patches
        merge_result = TreeReducePatchMerger().merge(
            round_id=round_id,
            patches=candidate_patches,
            prompt_ir=state.active_analysis_prompt.prompt_ir,
        )
        merged_patches = merge_result.final_patches

        if self.config.analysis_patch_semantic_merge_enabled and merged_patches:
            from mmap_optimizer.patch.semantic import SemanticPatchProcessor
            semantic_processor = SemanticPatchProcessor(self.optimizer_client, self._optimizer_model_config())
            merged_patches = semantic_processor.merge(merged_patches, state.active_analysis_prompt.prompt_ir)

        if not merged_patches:
            return AnalysisOptimizationResult(
                accepted=False,
                base_accuracy=base_acc,
                base_correct_count=base_correct,
                base_total_count=base_total,
                patched_accuracy=None, patched_correct_count=None, patched_total_count=None,
                patch_count=0, rejection_reason="analysis_merge_empty",
            )

        # Apply merged patches
        temp_prompt = state.active_analysis_prompt
        next_version = temp_prompt.version + 1
        for patch in merged_patches:
            temp_prompt = PatchApplier().apply(temp_prompt, patch, new_version=next_version)
            next_version += 1

        # Re-test analysis on error samples
        patched_results = []
        for sample in error_samples:
            blind_rec = blind_evaluation_records.get(sample.id)
            if blind_rec is None:
                continue
            result = AnalysisRunner(
                model_client=self.optimizer_client,
                model_id=self.config.optimizer_model.model,
                model_config=self._optimizer_model_config(),
            ).run_single_analysis(
                round_id=round_id,
                sample_id=sample.id,
                extraction_output=blind_rec.extraction_run_id,
                analysis_prompt=temp_prompt,
                ground_truth_label=blind_rec.ground_truth_label or blind_rec.voted_truth_label,
                metadata=sample.metadata,
            )
            patched_results.append(result)

        patched_correct = sum(1 for r in patched_results if r.get("matches_truth"))
        patched_total = len(patched_results)
        patched_acc = patched_correct / patched_total if patched_total else None

        # Accept if accuracy improved or stayed same
        if patched_acc is not None and patched_acc >= base_acc:
            state.active_analysis_prompt = temp_prompt
            return AnalysisOptimizationResult(
                accepted=True,
                base_accuracy=base_acc,
                base_correct_count=base_correct,
                base_total_count=base_total,
                patched_accuracy=patched_acc,
                patched_correct_count=patched_correct,
                patched_total_count=patched_total,
                patch_count=len(merged_patches),
                rejection_reason=None,
            )
        else:
            return AnalysisOptimizationResult(
                accepted=False,
                base_accuracy=base_acc,
                base_correct_count=base_correct,
                base_total_count=base_total,
                patched_accuracy=patched_acc,
                patched_correct_count=patched_correct,
                patched_total_count=patched_total,
                patch_count=0,
                rejection_reason="analysis_accuracy_degraded",
            )

    def _run_analysis_evolution(
        self,
        *,
        round_id: str,
        round_record,
        state: OptimizerState,
        extraction_result,
    ):
        """Run analysis prompt evolution driven by hard patch failures.

        Collects two signal categories from the current round:
        1. Extraction patches that failed schema/immutability/forbidden-section
           validation (rejection_reason captures the guard that fired).
        2. Extraction patches flagged as TOXIC by the regression / bundle
           retest phase.

        Delegates patch selection and application to
        ``AnalysisEvolutionEngine.evolve``, then persists the report under
        ``{round_id}/reports/{report.id}.json`` and promotes the active
        analysis prompt when the engine accepts the candidate.
        """
        from mmap_optimizer.analysis.evolution import AnalysisEvolutionEngine
        from mmap_optimizer.testing.patch_tester import PatchTestResult

        # (1) rejected extraction patches (schema / frozen / immutability)
        rejected_patches = [
            p for p in (extraction_result.draft_patches or [])
            if getattr(p, "status", None) == "rejected"
        ]
        rejected_patches.extend([
            p for p in (extraction_result.candidate_patches or [])
            if getattr(p, "status", None) == "rejected"
        ])

        # (2) toxic patch test results (derived from candidate patches that
        # were flagged by the re-test phase as toxic)
        toxic_patches = [
            p for p in (extraction_result.candidate_patches or [])
            if getattr(p, "toxicity_result", None) == "toxic"
        ]
        patch_test_results: list[PatchTestResult] = []
        for patch in toxic_patches:
            patch_test_results.append(
                PatchTestResult(
                    id=f"patch_test_{patch.id}",
                    round_id=round_id,
                    patch_id=patch.id,
                    test_suite_id=f"suite_{round_id}",
                    accepted=False,
                    toxicity_result="toxic",
                    broken_sample_ids=getattr(patch, "broken_sample_ids", None) or [],
                )
            )

        engine = AnalysisEvolutionEngine()
        report = engine.evolve(
            round_id=round_id,
            current_prompt=state.active_analysis_prompt,
            rejected_patches=rejected_patches,
            patch_test_results=patch_test_results,
        )

        # Persist the report for traceability — always, even when not promoted,
        # so the absence of a positive signal is itself observable.
        self.store.write_json(f"{round_id}/reports/{report.id}.json", report)
        # Also emit a well-known filename so external consumers and tests can
        # locate the evolution report without knowing the engine's id scheme.
        self.store.write_json(f"{round_id}/reports/analysis_evolution_report.json", report)

        if getattr(report, "promoted", False) and report.candidate_prompt is not None:
            state.active_analysis_prompt = report.candidate_prompt
            round_record.analysis_evolution_report_id = report.id
        else:
            round_record.analysis_evolution_report_id = report.id

        return report

    def _run_compression_stage(self, *, round_id: str, state: OptimizerState, optimization_batch: list, base_evaluations: list) -> tuple:
        """Run compression stage (extraction + analysis compression)."""
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
            token_budget=self.config.extraction_token_budget,
            samples=optimization_batch,
            assets=state.assets,
            ground_truths=state.ground_truths,
            contract=state.extraction_output_schema_contract,
            base_evaluations=base_evaluations,
        )
        compression_reports = [compression_report]
        if compression_report.accepted:
            state.active_extraction_prompt = compressed_prompt

        if self.config.analysis_line_budget is not None:
            analysis_compression_engine = CompressionEngine(
                model_client=self.optimizer_client,
                evaluator=self.evaluator,
                model_id=self.config.optimizer_model.model,
                model_config=self._optimizer_model_config(),
                enable_llm_compression=self.config.llm_compression_enabled,
                enable_json_repair=self.config.analysis_json_repair_enabled,
                json_repair_max_attempts=self.config.analysis_json_repair_max_attempts,
            )
            wrong_evals = [e for e in base_evaluations if e.overall_status != "correct"]
            analysis_compressed_prompt, analysis_compression_report, analysis_compression_runs, analysis_compression_evals = (
                analysis_compression_engine.compress_analysis_if_needed(
                    round_id=round_id,
                    prompt=state.active_analysis_prompt,
                    line_budget=self.config.analysis_line_budget,
                    token_budget=self.config.analysis_token_budget,
                    error_evaluations=wrong_evals,
                    sample_metadata={s.id: s.metadata for s in state.samples},
                    base_runs=[],
                )
            )
            compression_reports.append(analysis_compression_report)
            compression_runs.extend(analysis_compression_runs)
            compression_evals.extend(analysis_compression_evals)
            if analysis_compression_report.accepted:
                state.active_analysis_prompt = analysis_compressed_prompt

        return compression_reports, compression_runs, compression_evals

    def _run_fewshot_stage(self, *, round_id: str, round_index: int, state: OptimizerState, optimization_batch: list, base_evaluations: list) -> tuple:
        """Run fewshot stage."""
        fewshot_reports = []
        fewshot_runs = []
        fewshot_evals = []

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
            fewshot_pool = FewShotCandidatePool.from_mapping(
                self.store.read_json("fewshot_candidate_pool.json") if pool_path.exists() else None
            )
            fewshot_prompt, fewshot_report, fewshot_runs, fewshot_evals = fewshot_engine.optimize_once(
                round_id=round_id,
                prompt=state.active_extraction_prompt,
                samples=optimization_batch,
                assets=state.assets,
                ground_truths=state.ground_truths,
                sample_states=state.sample_states,
                contract=state.extraction_output_schema_contract,
                base_evaluations=base_evaluations,
                max_slots=self.config.fewshot_max_slots,
                min_accuracy_delta=self.config.fewshot_min_accuracy_delta,
                candidate_pool=fewshot_pool,
            )
            self.store.write_json("fewshot_candidate_pool.json", fewshot_pool)
            fewshot_reports.append(fewshot_report)
            if fewshot_report.accepted:
                state.active_extraction_prompt = fewshot_prompt

        return fewshot_reports, fewshot_runs, fewshot_evals

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
        all_suite = suite_builder.build_bundle_suite(round_id=round_id, patches=accepted_patches, current_evaluations=base_evaluations, canary_sample_ids=canary_sample_ids, historically_fixed_sample_ids=historically_fixed_sample_ids)
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
            trial_suite = suite_builder.build_bundle_suite(round_id=round_id, patches=trial, current_evaluations=base_evaluations, canary_sample_ids=canary_sample_ids, historically_fixed_sample_ids=historically_fixed_sample_ids)
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
            round_id = payload.pop("round_id", None)
            stage = payload.pop("stage", None)
            message = payload.pop("message", event_type)
            self.debug_logger.log(event_type, message, stage=stage, round_id=round_id, payload=payload)

    def _unique_patches(self, patches: list[Patch]) -> list[Patch]:
        by_id: dict[str, Patch] = {}
        for patch in patches:
            by_id[patch.id] = patch
        return list(by_id.values())

    def _save_intermediate(self, round_id: str, stage: str, data: dict) -> None:
        """Save intermediate results after each stage for debugging and audit.

        These files are written to {round_id}/intermediate/{stage}.json and
        removed by _cleanup_intermediate when the round completes successfully.
        They are NOT used for crash recovery (resume logic relies on
        OptimizerCheckpoint, not intermediate files). They serve as per-stage
        audit artifacts that survive only if the round crashes mid-execution.
        """
        self.store.write_json(f"{round_id}/intermediate/{stage}.json", data)

    def _advance_stage(self, round_id: str, round_record: OptimizationRound | None, stage: str) -> None:
        """Update current_stage and persist round_record for crash recovery."""
        if round_record is not None:
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
            was_correct = sample_state.consecutive_correct_count > 0
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
                if was_correct:
                    sample_state.toxic_trigger = True
                sample_state.consecutive_wrong_count += 1
                sample_state.consecutive_correct_count = 0
            else:
                if sample_state.consecutive_wrong_count > 0:
                    sample_state.historical_fixed = True
                sample_state.consecutive_correct_count += 1
                sample_state.consecutive_wrong_count = 0
