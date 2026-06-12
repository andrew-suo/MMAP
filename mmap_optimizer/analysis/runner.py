from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mmap_optimizer.analysis.record import AnalysisRecord
from mmap_optimizer.evaluation.evaluator import EvaluationRecord
from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.orchestration.records import RunRecord
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.prompt.version import PromptVersion


@dataclass
class AnalysisRunResult:
    analysis_records: list[AnalysisRecord]
    draft_patches: list[Patch]
    analysis_runs: list[RunRecord]


class AnalysisRunner:
    """Runs/parses analysis prompt outputs and normalizes patch candidates.

    The MVP runner supports deterministic tests by reading `mock_analysis_output` from
    sample metadata; otherwise it calls the configured model client with the same
    structured context shape.
    """

    def __init__(self, model_client: ModelClient, model_id: str = "mock-model"):
        self.model_client = model_client
        self.model_id = model_id

    def analyze_errors(
        self,
        *,
        round_id: str,
        error_evaluations: list[EvaluationRecord],
        extraction_runs: dict[str, RunRecord],
        sample_metadata: dict[str, dict[str, Any]],
        analysis_prompt: PromptVersion,
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
                    "content": {
                        "sample_id": evaluation.sample_id,
                        "evaluation": evaluation.__dict__,
                        "mock_output": mock_output,
                    },
                },
            ]
            response = self.model_client.complete(messages, model_config={"model": self.model_id})
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
            try:
                parsed = json.loads(response.raw_output)
            except json.JSONDecodeError:
                parsed = {"judgement": {"is_correct": False}, "patch_candidates": []}
                analysis_run.success = False
                analysis_run.error_type = "PARSE_ERROR"
            analysis_run.parsed_output = parsed
            source_run = extraction_runs[evaluation.sample_id]
            analysis_id = f"analysis_{round_id}_{evaluation.sample_id}"
            record = AnalysisRecord(
                id=analysis_id,
                round_id=round_id,
                extraction_run_id=source_run.id,
                evaluation_record_id=evaluation.id,
                sample_id=evaluation.sample_id,
                analysis_prompt_version_id=analysis_prompt.id,
                judgement=parsed.get("judgement", {}),
                judgement_matches_evaluator=parsed.get("judgement", {}).get("is_correct") == (evaluation.overall_status == "correct"),
            )
            for idx, candidate in enumerate(parsed.get("patch_candidates", []) or []):
                patch = self._patch_from_candidate(
                    candidate=candidate,
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
        section_id = candidate.get("target_section") or candidate.get("section_id") or "legacy_unmapped"
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
        )
