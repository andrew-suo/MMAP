from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mmap_optimizer.analysis.parser import parse_analysis_output_with_repair
from mmap_optimizer.analysis.record import AnalysisRecord
from mmap_optimizer.evaluation.evaluator import EvaluationRecord
from mmap_optimizer.logging import get_logger
from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.orchestration.records import (
    BlindEvaluationRecord,
    BlindEvaluationReflectionRecord,
    RunRecord,
)
from mmap_optimizer.prompt.version import PromptVersion

logger = get_logger(__name__)


@dataclass
class BlindEvaluationResult:
    """Result of blind evaluation analysis for a batch of samples."""

    blind_records: dict[str, BlindEvaluationRecord]
    reflection_records: list[BlindEvaluationReflectionRecord]
    analysis_runs: list[RunRecord]

    @property
    def samples_for_patch_generation(self) -> list[str]:
        """Return sample IDs where blind evaluation matches ground truth."""
        return [
            sample_id
            for sample_id, record in self.blind_records.items()
            if record.matches_truth
        ]

    @property
    def samples_excluded_from_patch(self) -> list[str]:
        """Return sample IDs where blind evaluation differs from ground truth."""
        return [
            sample_id
            for sample_id, record in self.blind_records.items()
            if not record.matches_truth
        ]

    @property
    def analysis_accuracy(self) -> float:
        """Ratio of samples where blind evaluation matched ground truth."""
        total = len(self.blind_records)
        if total == 0:
            return 0.0
        matched = sum(1 for r in self.blind_records.values() if r.matches_truth)
        return matched / total


class BlindEvaluationRunner:
    """Runs blind evaluation and reflection analysis for prompt optimization.

    Step 3 in the 7-step extraction prompt optimization pipeline:
    1. Blind analysis: run analysis prompt WITHOUT ground truth
    2. Truth comparison: compare blind judgement with ground truth
       (fallback: 3-analysis majority vote)
    3. Reflection: for "correct but misjudged" samples, generate reflection
       records to train the analysis prompt optimization loop
    """

    def __init__(
        self,
        model_client: ModelClient,
        model_id: str = "mock-model",
        model_config: dict[str, Any] | None = None,
        *,
        enable_json_repair: bool = False,
        json_repair_max_attempts: int = 1,
        three_analysis_vote_enabled: bool = True,
    ):
        self.model_client = model_client
        self.model_id = model_id
        self.model_config = model_config or {"model": model_id}
        self.enable_json_repair = enable_json_repair
        self.json_repair_max_attempts = json_repair_max_attempts
        self.three_analysis_vote_enabled = three_analysis_vote_enabled

    def run_blind_evaluation(
        self,
        *,
        round_id: str,
        evaluations: list[EvaluationRecord],
        extraction_runs: dict[str, RunRecord],
        sample_metadata: dict[str, dict[str, Any]],
        analysis_prompt: PromptVersion,
        ground_truths: dict[str, Any] | None = None,
    ) -> BlindEvaluationResult:
        """Run blind evaluation on all evaluated samples.

        For each sample:
        - Run analysis prompt (without giving it ground truth)
        - Get ground truth label (from sample_metadata or voted from 3 analyses)
        - Compare blind judgement with truth
        """
        rendered = analysis_prompt.render()
        blind_records: dict[str, BlindEvaluationRecord] = {}
        analysis_runs: list[RunRecord] = []

        for evaluation in evaluations:
            source_run = extraction_runs.get(evaluation.sample_id)
            if source_run is None:
                logger.warning(
                    "No extraction run found for sample_id=%s, skipping blind eval",
                    evaluation.sample_id,
                )
                continue

            metadata = sample_metadata.get(evaluation.sample_id, {})
            mock_output = metadata.get("mock_analysis_output")

            # Step 3a: Run blind analysis (model does NOT see ground truth)
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
                id=f"run_{round_id}_blind_{evaluation.sample_id}",
                round_id=round_id,
                run_type="blind_evaluation",
                sample_id=evaluation.sample_id,
                prompt_version_id=analysis_prompt.id,
                rendered_prompt_hash=rendered.text_hash,
                model_id=self.model_id,
                raw_output=response.raw_output,
            )
            analysis_runs.append(analysis_run)

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

            # Extract blind judgement
            judgement = parse_result.parsed.get("judgement", {}) if isinstance(parse_result.parsed, dict) else {}
            if isinstance(judgement, dict):
                blind_judgement = str(judgement.get("primary_label", ""))
            else:
                blind_judgement = str(judgement)

            # Step 3b: Compare with ground truth
            ground_truth_label = self._extract_ground_truth_label(
                evaluation, ground_truths, metadata
            )

            if ground_truth_label is not None:
                resolved_truth = ground_truth_label
                used_voted_truth = False
            elif self.three_analysis_vote_enabled:
                # No ground truth: run 3 independent analyses and vote
                voted_truth, three_outputs = self._run_three_analysis_vote(
                    round_id=round_id,
                    evaluation=evaluation,
                    source_run=source_run,
                    metadata=metadata,
                    analysis_prompt=analysis_prompt,
                )
                resolved_truth = voted_truth or blind_judgement
                used_voted_truth = voted_truth is not None
            else:
                # No ground truth and no voting: treat blind judgement as truth
                resolved_truth = blind_judgement
                used_voted_truth = False

            matches_truth = blind_judgement == resolved_truth

            record = BlindEvaluationRecord(
                id=f"blind_{round_id}_{evaluation.sample_id}",
                round_id=round_id,
                sample_id=evaluation.sample_id,
                extraction_run_id=source_run.id,
                analysis_prompt_version_id=analysis_prompt.id,
                blind_judgement=blind_judgement,
                ground_truth_label=ground_truth_label,
                voted_truth_label=resolved_truth if used_voted_truth else None,
                three_analysis_outputs=three_outputs if used_voted_truth and "three_outputs" in locals() else None,
                matches_truth=matches_truth,
                overall_status=evaluation.overall_status,
                parse_success=parse_result.parse_success,
                schema_valid=parse_result.schema_valid,
                raw_output=response.raw_output,
                parsed_output=parse_result.parsed,
            )
            blind_records[evaluation.sample_id] = record

        # Step 3d: Generate reflection records for "correct but misjudged" samples
        reflection_records = self._generate_reflections(
            round_id=round_id,
            evaluations=evaluations,
            blind_records=blind_records,
            analysis_prompt=analysis_prompt,
        )

        return BlindEvaluationResult(
            blind_records=blind_records,
            reflection_records=reflection_records,
            analysis_runs=analysis_runs,
        )

    def _extract_ground_truth_label(
        self,
        evaluation: EvaluationRecord,
        ground_truths: dict[str, Any] | None,
        metadata: dict[str, Any],
    ) -> str | None:
        """Extract ground truth label from available sources."""
        # Try normalized_ground_truth from evaluation
        if evaluation.normalized_ground_truth is not None:
            if isinstance(evaluation.normalized_ground_truth, dict):
                label = evaluation.normalized_ground_truth.get("primary_label") or evaluation.normalized_ground_truth.get("result")
                if label:
                    return str(label)
            return str(evaluation.normalized_ground_truth)

        # Try ground_truths dict
        if ground_truths and evaluation.sample_id in ground_truths:
            gt = ground_truths[evaluation.sample_id]
            if isinstance(gt, dict):
                label = gt.get("primary_label") or gt.get("result") or gt.get("expected_output")
                if label:
                    return str(label)
            if isinstance(gt, str):
                return gt

        # Try metadata mock_ground_truth
        mock_gt = metadata.get("mock_ground_truth")
        if mock_gt:
            if isinstance(mock_gt, dict):
                return str(mock_gt.get("primary_label", ""))
            return str(mock_gt)

        return None

    def _run_three_analysis_vote(
        self,
        *,
        round_id: str,
        evaluation: EvaluationRecord,
        source_run: RunRecord,
        metadata: dict[str, Any],
        analysis_prompt: PromptVersion,
    ) -> tuple[str | None, list[dict]]:
        """Run 3 independent analyses and use majority vote as ground truth proxy."""
        rendered = analysis_prompt.render()
        mock_output = metadata.get("mock_analysis_output")
        judgements: list[str] = []
        outputs: list[dict] = []

        for i in range(3):
            messages = [
                {"role": "system", "content": rendered.text},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "sample_id": evaluation.sample_id,
                            "evaluation": evaluation.__dict__,
                            "mock_output": mock_output,
                            "analysis_round": i + 1,
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            response = self.model_client.complete(messages, model_config=self.model_config)
            parse_result = parse_analysis_output_with_repair(
                response.raw_output,
                repair_client=self.model_client,
                repair_model_config=self.model_config,
                enable_llm_repair=self.enable_json_repair,
                max_attempts=self.json_repair_max_attempts,
            )
            judgement = parse_result.parsed.get("judgement", {}) if isinstance(parse_result.parsed, dict) else {}
            if isinstance(judgement, dict):
                label = str(judgement.get("primary_label", ""))
            else:
                label = str(judgement)
            judgements.append(label)
            outputs.append({"raw_output": response.raw_output, "parsed": parse_result.parsed})

        # Majority vote
        from collections import Counter
        if judgements:
            counter = Counter(judgements)
            most_common = counter.most_common(1)[0][0]
            if most_common:
                return most_common, outputs

        return None, outputs

    def _generate_reflections(
        self,
        *,
        round_id: str,
        evaluations: list[EvaluationRecord],
        blind_records: dict[str, BlindEvaluationRecord],
        analysis_prompt: PromptVersion,
    ) -> list[BlindEvaluationReflectionRecord]:
        """Generate reflection records for analysis prompt optimization.

        Targets: samples that are "correct in extraction but misjudged by analysis"
        (overall_status == "correct" and matches_truth == False).
        These indicate the analysis prompt is giving wrong signals.
        """
        reflections: list[BlindEvaluationReflectionRecord] = []
        correct_evals = [e for e in evaluations if e.overall_status == "correct"]

        for evaluation in correct_evals:
            blind_record = blind_records.get(evaluation.sample_id)
            if blind_record is None:
                continue
            if blind_record.matches_truth:
                continue  # Analysis got it right — no reflection needed

            # Analysis misjudged a correct sample — generate reflection
            reflection_prompt = (
                "You just analyzed an extraction output and made a judgement "
                "that turned out to be wrong. The sample was actually correctly "
                "extracted but your analysis said otherwise. "
                "Please reflect on: "
                "(1) why your blind analysis was wrong, "
                "(2) what specific signals or checks you missed, "
                "(3) how you would improve your analysis approach for similar cases. "
                "Respond with JSON: {\"why_wrong\": \"...\", "
                "\"should_have_checked\": \"...\", \"how_to_improve\": \"...\"}"
            )

            messages = [
                {"role": "system", "content": reflection_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "sample_id": evaluation.sample_id,
                            "blind_judgement": blind_record.blind_judgement,
                            "ground_truth": blind_record.ground_truth_label or blind_record.voted_truth_label or "correct",
                            "overall_status": evaluation.overall_status,
                        },
                        ensure_ascii=False,
                    ),
                },
            ]

            response = self.model_client.complete(messages, model_config=self.model_config)

            parsed_reflection: dict | None = None
            try:
                parsed_reflection = json.loads(response.raw_output)
            except (json.JSONDecodeError, TypeError):
                parsed_reflection = {"raw": response.raw_output}

            why_wrong = ""
            should_have_checked = ""
            how_to_improve = ""
            if isinstance(parsed_reflection, dict):
                why_wrong = str(parsed_reflection.get("why_wrong", ""))
                should_have_checked = str(parsed_reflection.get("should_have_checked", ""))
                how_to_improve = str(parsed_reflection.get("how_to_improve", ""))

            reflection = BlindEvaluationReflectionRecord(
                id=f"reflection_{round_id}_{evaluation.sample_id}",
                round_id=round_id,
                sample_id=evaluation.sample_id,
                analysis_prompt_version_id=analysis_prompt.id,
                original_blind_judgement=blind_record.blind_judgement,
                ground_truth_label=blind_record.ground_truth_label or blind_record.voted_truth_label or "correct",
                why_blind_was_wrong=why_wrong,
                what_should_have_been_checked=should_have_checked,
                how_to_improve_analysis=how_to_improve,
                raw_reflection_output=response.raw_output,
                parsed_reflection=parsed_reflection,
                used_voted_truth=blind_record.voted_truth_label is not None,
            )
            reflections.append(reflection)

        return reflections
