from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from mmap_optimizer.core.enums import PromptVersionType, RunType
from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset, SampleState
from mmap_optimizer.evaluation.evaluator import EvaluationRecord, Evaluator
from mmap_optimizer.fewshot.report import FewShotOptimizationReport
from mmap_optimizer.fewshot.schema import FewShotCandidate, FewShotExample, FewShotSetVersion
from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.ir import PromptSection
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.testing.prompt_test_runner import PromptTestRunner


class FewShotOptimizationEngine:
    """Greedy few-shot slot optimizer for stable text prompts.

    The engine mines currently failed samples, generates schema-valid examples from
    ground truth, tests one candidate slot at a time, and promotes only candidates
    with no regressions on samples that were already correct.
    """

    SECTION_ID = "few_shot_examples"

    def __init__(self, *, model_client: ModelClient, evaluator: Evaluator, model_id: str = "mock-model"):
        self.model_client = model_client
        self.evaluator = evaluator
        self.model_id = model_id

    def optimize_once(
        self,
        *,
        round_id: str,
        prompt: PromptVersion,
        samples: list[Sample],
        assets: dict[str, SampleAsset],
        ground_truths: dict[str, GroundTruth],
        sample_states: dict[str, SampleState],
        contract: OutputSchemaContract,
        base_evaluations: list[EvaluationRecord],
        max_slots: int,
        min_accuracy_delta: float = 0.0,
    ) -> tuple[PromptVersion, FewShotOptimizationReport, list, list[EvaluationRecord]]:
        slot_count = self._slot_count(prompt)
        baseline_accuracy = self._accuracy(base_evaluations)
        report = FewShotOptimizationReport(
            id=f"fewshot_{round_id}_extraction",
            round_id=round_id,
            prompt_version_before_id=prompt.id,
            triggered=False,
            reason="NO_SLOT_CAPACITY" if slot_count >= max_slots else "READY",
            slot_count_before=slot_count,
            slot_count_after=slot_count,
            max_slots=max_slots,
            baseline_accuracy=baseline_accuracy,
        )
        if max_slots <= 0:
            report.reason = "DISABLED"
            return prompt, report, [], []
        if slot_count >= max_slots:
            return prompt, report, [], []

        report.triggered = True
        baseline_by_sample = {evaluation.sample_id: evaluation for evaluation in base_evaluations}
        behavior_samples = [sample for sample in samples if sample.id in baseline_by_sample]
        candidates = self._mine_candidates(base_evaluations, sample_states)
        report.candidate_count = len(candidates)
        if not candidates:
            report.failure_reason = "NO_FAILED_SAMPLE_CANDIDATES"
            return prompt, report, [], []

        all_runs = []
        all_evaluations: list[EvaluationRecord] = []
        best_safe: tuple[float, PromptVersion, FewShotOptimizationReport] | None = None
        sample_by_id = {sample.id: sample for sample in samples}
        for candidate in candidates:
            source_sample = sample_by_id.get(candidate.sample_id)
            if source_sample is None:
                candidate.eligible = False
                candidate.rejection_reason = "SAMPLE_NOT_FOUND"
                report.rejected_candidates.append({"candidate_id": candidate.id, "reason": candidate.rejection_reason})
                continue
            example = self._generate_example(candidate, source_sample, ground_truths[source_sample.ground_truth_id], contract)
            if not example.schema_valid or not example.matches_ground_truth:
                candidate.eligible = False
                candidate.rejection_reason = "EXAMPLE_CONTRACT_FAILED"
                report.rejected_candidates.append({"candidate_id": candidate.id, "reason": candidate.rejection_reason})
                continue
            candidate_prompt, fewshot_set = self._candidate_prompt(prompt, example, new_version=prompt.version + 1)
            run_result = PromptTestRunner(
                model_client=self.model_client,
                evaluator=self.evaluator,
                model_id=self.model_id,
            ).run(
                round_id=round_id,
                run_type=RunType.FEW_SHOT_TEST.value,
                prompt=candidate_prompt,
                samples=behavior_samples,
                assets=assets,
                ground_truths=ground_truths,
                contract=contract,
                run_id_suffix=candidate.id,
            )
            all_runs.extend(run_result.runs)
            all_evaluations.extend(run_result.evaluations)
            broken, schema_violations = self._regressions(baseline_by_sample, run_result.evaluations)
            candidate_accuracy = self._accuracy(run_result.evaluations)
            delta = candidate_accuracy - baseline_accuracy
            if broken or schema_violations or delta < min_accuracy_delta:
                candidate.rejection_reason = "FEWSHOT_REGRESSION_OR_INSUFFICIENT_GAIN"
                report.rejected_candidates.append(
                    {
                        "candidate_id": candidate.id,
                        "sample_id": candidate.sample_id,
                        "accuracy_delta": delta,
                        "broken_sample_ids": broken,
                        "schema_violation_sample_ids": schema_violations,
                        "reason": candidate.rejection_reason,
                    }
                )
                continue
            candidate_report = replace(report)
            candidate_report.accepted = True
            candidate_report.reason = "ACCEPTED"
            candidate_report.prompt_version_after_id = candidate_prompt.id
            candidate_report.fewshot_set_version_id = fewshot_set.id
            candidate_report.selected_candidate_id = candidate.id
            candidate_report.selected_sample_id = candidate.sample_id
            candidate_report.slot_count_after = slot_count + 1
            candidate_report.candidate_accuracy = candidate_accuracy
            candidate_report.accuracy_delta = delta
            candidate_report.broken_sample_ids = broken
            candidate_report.schema_violation_sample_ids = schema_violations
            if best_safe is None or delta > best_safe[0]:
                best_safe = (delta, candidate_prompt, candidate_report)

        if best_safe is not None:
            _, best_prompt, best_report = best_safe
            return best_prompt, best_report, all_runs, all_evaluations

        report.failure_reason = "NO_SAFE_FEWSHOT_CANDIDATE"
        return prompt, report, all_runs, all_evaluations

    def _mine_candidates(self, base_evaluations: list[EvaluationRecord], sample_states: dict[str, SampleState]) -> list[FewShotCandidate]:
        candidates: list[FewShotCandidate] = []
        for evaluation in base_evaluations:
            if evaluation.overall_status == "correct":
                continue
            state = sample_states.get(evaluation.sample_id, SampleState(sample_id=evaluation.sample_id))
            score = 1.0 + state.difficulty_ema + 0.1 * state.consecutive_wrong_count
            candidates.append(FewShotCandidate(id=f"fewshot_candidate_{evaluation.sample_id}", sample_id=evaluation.sample_id, candidate_score=score))
        return sorted(candidates, key=lambda candidate: candidate.candidate_score, reverse=True)

    def _generate_example(self, candidate: FewShotCandidate, sample: Sample, ground_truth: GroundTruth, contract: OutputSchemaContract) -> FewShotExample:
        final_output = self._schema_complete_output(ground_truth.value, ground_truth.primary_answer, contract)
        schema_result = self.evaluator.validator.validate(final_output, contract.schema)
        primary_matches = all(final_output.get(field) == ground_truth.value.get(field, ground_truth.primary_answer) for field in contract.primary_answer_fields)
        reasoning_text = sample.metadata.get("fewshot_reasoning") or "根据图像和上下文证据，按输出 schema 给出与 ground truth 一致的审核结论。"
        return FewShotExample(
            id=f"fewshot_example_{sample.id}",
            candidate_id=candidate.id,
            source_sample_id=sample.id,
            asset_ids=sample.asset_ids,
            reasoning_text=reasoning_text,
            final_output=final_output,
            schema_valid=schema_result.valid,
            matches_ground_truth=primary_matches,
            visual_evidence_grounded=sample.metadata.get("fewshot_visual_evidence_grounded"),
            status="validated" if schema_result.valid and primary_matches else "rejected",
        )

    def _candidate_prompt(self, prompt: PromptVersion, example: FewShotExample, *, new_version: int) -> tuple[PromptVersion, FewShotSetVersion]:
        existing = prompt.prompt_ir.section_by_id(self.SECTION_ID)
        existing_content = existing.content.strip() if existing is not None else ""
        example_block = self._render_example(example, slot_index=self._slot_count(prompt) + 1)
        new_content = "\n\n".join(chunk for chunk in [existing_content, example_block] if chunk)
        if existing is None:
            sections = [
                *prompt.prompt_ir.sections,
                PromptSection(
                    id=self.SECTION_ID,
                    type="few_shot_examples",
                    content=new_content,
                    name="Few-shot examples",
                    scope="framework",
                    priority="high",
                    compressibility="low",
                    mutability="limited",
                ),
            ]
            rendering_order = [*prompt.prompt_ir.rendering_order, self.SECTION_ID]
            new_ir = replace(prompt.prompt_ir, sections=sections, rendering_order=rendering_order, version=new_version, parent_prompt_ir_id=prompt.prompt_ir.id)
        else:
            new_ir = prompt.prompt_ir.with_replaced_section(self.SECTION_ID, new_content)
            new_ir = replace(new_ir, version=new_version, parent_prompt_ir_id=prompt.prompt_ir.id)
        prompt_type_value = getattr(prompt.prompt_type, "value", str(prompt.prompt_type))
        fewshot_set = FewShotSetVersion(
            id=f"fewshot_set_{prompt_type_value}_v{new_version}",
            base_text_prompt_version_id=prompt.id,
            version=new_version,
            slot_count=self._slot_count(prompt) + 1,
            slots=[{"slot_index": self._slot_count(prompt) + 1, "example_id": example.id, "source_sample_id": example.source_sample_id}],
            status="accepted",
        )
        candidate_prompt = PromptVersion(
            id=f"{prompt_type_value}_prompt_v{new_version}",
            prompt_type=prompt.prompt_type,
            version=new_version,
            prompt_ir=new_ir,
            output_schema_contract_id=prompt.output_schema_contract_id,
            version_type=PromptVersionType.FEW_SHOT_OPTIMIZATION,
            parent_version_id=prompt.id,
            applied_patch_ids=[*prompt.applied_patch_ids],
            compression_patch_ids=[*prompt.compression_patch_ids],
        )
        candidate_prompt.render()
        return candidate_prompt, fewshot_set

    def _render_example(self, example: FewShotExample, *, slot_index: int) -> str:
        return "\n".join(
            [
                f"FEW_SHOT_SLOT:{slot_index}",
                f"FEW_SHOT_SAMPLE:{example.source_sample_id}",
                "分析过程示例:",
                example.reasoning_text,
                "最终输出示例:",
                json.dumps(example.final_output, ensure_ascii=False, sort_keys=True),
            ]
        )

    def _schema_complete_output(self, value: dict[str, Any], primary_answer: Any, contract: OutputSchemaContract) -> dict[str, Any]:
        output = dict(value)
        for field in contract.primary_answer_fields:
            output.setdefault(field, primary_answer)
        for field in contract.schema.get("required", []) or []:
            if field in output:
                continue
            prop_type = (contract.schema.get("properties", {}).get(field, {}) or {}).get("type")
            if prop_type == "number":
                output[field] = 1.0
            elif prop_type == "array":
                output[field] = []
            elif prop_type == "object":
                output[field] = {}
            elif prop_type == "boolean":
                output[field] = True
            else:
                output[field] = str(primary_answer)
        return output

    def _slot_count(self, prompt: PromptVersion) -> int:
        section = prompt.prompt_ir.section_by_id(self.SECTION_ID)
        if section is None or not section.content.strip():
            return 0
        return sum(1 for line in section.content.splitlines() if line.startswith("FEW_SHOT_SLOT:"))

    def _regressions(self, baseline_by_sample: dict[str, EvaluationRecord], candidate_evaluations: list[EvaluationRecord]) -> tuple[list[str], list[str]]:
        broken: list[str] = []
        schema_violations: list[str] = []
        for candidate in candidate_evaluations:
            baseline = baseline_by_sample[candidate.sample_id]
            if candidate.overall_status in {"parse_error", "schema_error"} or not candidate.schema_valid:
                schema_violations.append(candidate.sample_id)
            if baseline.overall_status == "correct" and candidate.overall_status != "correct":
                broken.append(candidate.sample_id)
        return broken, schema_violations

    def _accuracy(self, evaluations: list[EvaluationRecord]) -> float:
        if not evaluations:
            return 0.0
        return sum(1 for evaluation in evaluations if evaluation.overall_status == "correct") / len(evaluations)
