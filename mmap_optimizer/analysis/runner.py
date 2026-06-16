from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mmap_optimizer.analysis.parser import parse_analysis_output_with_repair
from mmap_optimizer.analysis.record import AnalysisRecord
from mmap_optimizer.evaluation.evaluator import EvaluationRecord
from mmap_optimizer.logging import get_logger
from mmap_optimizer.model.client import ModelClient

logger = get_logger(__name__)
from mmap_optimizer.orchestration.records import RunRecord
from mmap_optimizer.patch.alignment import PatchAlignmentEngine
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.prompt.version import PromptVersion


@dataclass
class AnalysisRunResult:
    analysis_records: list[AnalysisRecord]
    draft_patches: list[Patch]
    analysis_runs: list[RunRecord]


class AnalysisRunner:
    """Runs/parses analysis prompt outputs and normalizes patch candidates.

    The runner accepts deterministic mock analysis output from sample metadata, but
    production outputs go through repair, schema checks, and per-candidate
    validation so malformed analysis never aborts the round.
    """

    def __init__(
        self,
        model_client: ModelClient,
        model_id: str = "mock-model",
        model_config: dict[str, Any] | None = None,
        *,
        enable_json_repair: bool = False,
        json_repair_max_attempts: int = 1,
    ):
        self.model_client = model_client
        self.model_id = model_id
        self.model_config = model_config or {"model": model_id}
        self.enable_json_repair = enable_json_repair
        self.json_repair_max_attempts = json_repair_max_attempts

    def analyze_errors(
        self,
        *,
        round_id: str,
        error_evaluations: list[EvaluationRecord],
        extraction_runs: dict[str, RunRecord],
        sample_metadata: dict[str, dict[str, Any]],
        analysis_prompt: PromptVersion,
        target_prompt: PromptVersion | None = None,
    ) -> AnalysisRunResult:
        rendered = analysis_prompt.render()
        records: list[AnalysisRecord] = []
        patches: list[Patch] = []
        runs: list[RunRecord] = []
        for evaluation in error_evaluations:
            metadata = sample_metadata.get(evaluation.sample_id, {})
            mock_output = metadata.get("mock_analysis_output")
            messages = [
                {"role": "system", "content": rendered.text},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "sample_id": evaluation.sample_id,
                            "evaluation": evaluation.__dict__,
                            "mock_output": mock_output,
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            response = self.model_client.complete(messages, model_config=self.model_config)
            analysis_run = RunRecord(
                id=f"run_{round_id}_analysis_{evaluation.sample_id}",
                round_id=round_id,
                run_type="analysis",
                sample_id=evaluation.sample_id,
                prompt_version_id=analysis_prompt.id,
                rendered_prompt_hash=rendered.text_hash,
                model_id=self.model_id,
                raw_output=response.raw_output,
            )
            parse_result = parse_analysis_output_with_repair(
                response.raw_output,
                repair_client=self.model_client,
                repair_model_config=self.model_config,
                enable_llm_repair=self.enable_json_repair,
                max_attempts=self.json_repair_max_attempts,
            )
            analysis_run.parsed_output = parse_result.parsed
            if not parse_result.parse_success:
                analysis_run.success = False
                analysis_run.error_type = "PARSE_ERROR"
            elif not parse_result.schema_valid:
                analysis_run.success = False
                analysis_run.error_type = "SCHEMA_ERROR"
            source_run = extraction_runs.get(evaluation.sample_id)
            if source_run is None:
                logger.warning(
                    "No extraction run found for sample_id=%s, skipping analysis",
                    evaluation.sample_id,
                )
                continue
            analysis_id = f"analysis_{round_id}_{evaluation.sample_id}"
            judgement = parse_result.parsed.get("judgement", {}) if isinstance(parse_result.parsed, dict) else {}
            record = AnalysisRecord(
                id=analysis_id,
                round_id=round_id,
                extraction_run_id=source_run.id,
                evaluation_record_id=evaluation.id,
                sample_id=evaluation.sample_id,
                analysis_prompt_version_id=analysis_prompt.id,
                judgement=judgement,
                judgement_matches_evaluator=judgement.get("is_correct") == (evaluation.overall_status == "correct"),
                parse_success=parse_result.parse_success,
                schema_valid=parse_result.schema_valid,
                parse_error=";".join(parse_result.errors) if not parse_result.parse_success else None,
                schema_errors=parse_result.errors if parse_result.parse_success and not parse_result.schema_valid else [],
                repaired=parse_result.repaired,
                repair_actions=parse_result.repair_actions,
                invalid_patch_candidate_count=len(parse_result.invalid_patch_candidates),
                invalid_patch_count=len(parse_result.invalid_patch_candidates),
            )
            for idx, candidate in enumerate(parse_result.valid_patch_candidates):
                normalized_candidate = candidate
                if target_prompt is not None:
                    alignment = PatchAlignmentEngine().align_patch_location(candidate, target_prompt.prompt_ir)
                    normalized_candidate = alignment.aligned_patch
                patch = self._patch_from_candidate(
                    candidate=normalized_candidate,
                    round_id=round_id,
                    index=idx,
                    base_version_id=source_run.prompt_version_id,
                    sample_id=evaluation.sample_id,
                    analysis_id=analysis_id,
                )
                patches.append(patch)
                record.patch_candidate_ids.append(patch.id)
            record.generated_patch_count = len(record.patch_candidate_ids)
            records.append(record)
            runs.append(analysis_run)
        return AnalysisRunResult(records, patches, runs)

    def _patch_from_candidate(self, *, candidate: dict[str, Any], round_id: str, index: int, base_version_id: str, sample_id: str, analysis_id: str) -> Patch:
        section_id = candidate.get("section_id") or candidate.get("target_section") or "legacy_unmapped"
        operation = candidate.get("operation") or "ADD_RULE"
        return Patch(
            id=f"patch_{round_id}_{sample_id}_{index:02d}",
            type="prompt_patch",
            status="draft",
            target_prompt_type=candidate.get("target_prompt", "extraction"),
            base_version_id=base_version_id,
            section_id=section_id,
            operation_type=operation,
            operation_mode=candidate.get("mode", "append"),
            intent_name=candidate.get("intent", "analysis_generated_patch"),
            intent_description=candidate.get("intent_description", candidate.get("intent", "analysis generated patch")),
            patch_text=candidate.get("content", ""),
            rationale=candidate.get("rationale", "generated from analysis output"),
            source_sample_ids=[sample_id],
            source_analysis_ids=[analysis_id],
            risk_level=candidate.get("risk_level", "unknown"),
            possible_side_effects=[candidate["risk"]] if isinstance(candidate.get("risk"), str) else candidate.get("possible_side_effects", []),
            old_text=candidate.get("old_text"),
            target_text=candidate.get("target_text"),
            new_text=candidate.get("new_text"),
        )
