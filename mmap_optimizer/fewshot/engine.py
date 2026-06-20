from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from mmap_optimizer.core.enums import PromptVersionType, RunType
from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset, SampleState
from mmap_optimizer.evaluation.evaluator import EvaluationRecord, Evaluator
from mmap_optimizer.fewshot.pool import FewShotCandidatePool
from mmap_optimizer.fewshot.report import FewShotOptimizationReport
from mmap_optimizer.fewshot.schema import FewShotCandidate, FewShotExample, FewShotSetVersion
from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.ir import PromptSection
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.testing.prompt_test_runner import PromptTestRunner


class FewShotOptimizationEngine:
    """Greedy few-shot slot optimizer for stable text prompts.

    The engine mines failed samples into a cross-round candidate pool, generates
    schema-valid examples, tests candidate prompts and bundle prompts, and can
    either add a new slot or replace an existing slot when capacity is full.
    """

    SECTION_ID = "few_shot_examples"

    def __init__(
        self,
        *,
        model_client: ModelClient,
        evaluator: Evaluator,
        model_id: str = "mock-model",
        model_config: dict | None = None,
        reasoning_model_client: ModelClient | None = None,
        reasoning_model_config: dict | None = None,
    ):
        self.model_client = model_client
        self.evaluator = evaluator
        self.model_id = model_id
        self.model_config = model_config or {"model": model_id}
        self.reasoning_model_client = reasoning_model_client
        self.reasoning_model_config = reasoning_model_config or self.model_config

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
        candidate_pool: FewShotCandidatePool | None = None,
    ) -> tuple[PromptVersion, FewShotOptimizationReport, list, list[EvaluationRecord]]:
        candidate_pool = candidate_pool or FewShotCandidatePool()
        slots = self._parse_slots(prompt)
        slot_count = len(slots)
        baseline_accuracy = self._accuracy(base_evaluations)
        report = FewShotOptimizationReport(
            id=f"fewshot_{round_id}_extraction",
            round_id=round_id,
            prompt_version_before_id=prompt.id,
            triggered=False,
            reason="READY",
            slot_count_before=slot_count,
            slot_count_after=slot_count,
            max_slots=max_slots,
            baseline_accuracy=baseline_accuracy,
            candidate_pool_size=len(candidate_pool.candidates),
        )
        if max_slots <= 0:
            report.reason = "DISABLED"
            return prompt, report, [], []

        mined = self._mine_candidates(base_evaluations, sample_states)
        for candidate in mined:
            state = sample_states.get(candidate.sample_id, SampleState(sample_id=candidate.sample_id))
            candidate_pool.add_mined(round_id=round_id, candidate=candidate, difficulty_ema=state.difficulty_ema)
        candidates = self._dedupe_candidates([*candidate_pool.eligible_candidates(), *mined])
        report.candidate_count = len(candidates)
        report.candidate_pool_size = len(candidate_pool.candidates)
        if not candidates:
            report.failure_reason = "NO_FAILED_SAMPLE_CANDIDATES"
            return prompt, report, [], []

        report.triggered = True
        baseline_by_sample = {evaluation.sample_id: evaluation for evaluation in base_evaluations}
        behavior_samples = [sample for sample in samples if sample.id in baseline_by_sample]
        all_runs = []
        all_evaluations: list[EvaluationRecord] = []
        best_safe: tuple[float, PromptVersion, FewShotOptimizationReport] | None = None
        sample_by_id = {sample.id: sample for sample in samples}
        existing_sample_ids = {slot.get("source_sample_id") for slot in slots}
        for candidate in candidates:
            if candidate.sample_id in existing_sample_ids:
                continue
            source_sample = sample_by_id.get(candidate.sample_id)
            if source_sample is None:
                candidate.rejection_reason = "SAMPLE_NOT_FOUND"
                report.rejected_candidates.append({"candidate_id": candidate.id, "reason": candidate.rejection_reason})
                candidate_pool.mark_tested(candidate_id=candidate.id, round_id=round_id, accuracy_delta=0.0, accepted=False, rejection_reason=candidate.rejection_reason)
                continue
            ground_truth = ground_truths.get(source_sample.ground_truth_id)
            if ground_truth is None:
                candidate.rejection_reason = "GROUND_TRUTH_NOT_FOUND"
                report.rejected_candidates.append({"candidate_id": candidate.id, "reason": candidate.rejection_reason})
                candidate_pool.mark_tested(candidate_id=candidate.id, round_id=round_id, accuracy_delta=0.0, accepted=False, rejection_reason=candidate.rejection_reason)
                continue
            example = self._generate_example(candidate, source_sample, ground_truth, contract)
            if not example.schema_valid or not example.matches_ground_truth:
                candidate.rejection_reason = "EXAMPLE_CONTRACT_FAILED"
                report.rejected_candidates.append({"candidate_id": candidate.id, "reason": candidate.rejection_reason})
                candidate_pool.mark_tested(candidate_id=candidate.id, round_id=round_id, accuracy_delta=0.0, accepted=False, rejection_reason=candidate.rejection_reason)
                continue
            operation_type = "ADD_SLOT" if slot_count < max_slots else "REPLACE_SLOT"
            replace_slot = None if operation_type == "ADD_SLOT" else self._replacement_slot(slots)
            candidate_prompt, fewshot_set = self._candidate_prompt(prompt, example, new_version=prompt.version + 1, max_slots=max_slots, replace_slot=replace_slot)
            run_result = self._run_prompt(round_id, candidate_prompt, behavior_samples, assets, ground_truths, contract, candidate.id, RunType.FEW_SHOT_TEST.value)
            all_runs.extend(run_result.runs)
            all_evaluations.extend(run_result.evaluations)
            broken, schema_violations = self._regressions(baseline_by_sample, run_result.evaluations)
            candidate_accuracy = self._accuracy(run_result.evaluations)
            delta = candidate_accuracy - baseline_accuracy
            if broken or schema_violations or delta < min_accuracy_delta:
                candidate.rejection_reason = "FEWSHOT_REGRESSION_OR_INSUFFICIENT_GAIN"
                self._record_rejection(report, candidate, delta, broken, schema_violations, candidate.rejection_reason)
                candidate_pool.mark_tested(candidate_id=candidate.id, round_id=round_id, accuracy_delta=delta, accepted=False, rejection_reason=candidate.rejection_reason, broken_sample_ids=broken)
                continue

            bundle_result = self._run_prompt(round_id, candidate_prompt, behavior_samples, assets, ground_truths, contract, f"bundle_{candidate.id}", "few_shot_bundle_test")
            all_runs.extend(bundle_result.runs)
            all_evaluations.extend(bundle_result.evaluations)
            bundle_broken, bundle_schema = self._regressions(baseline_by_sample, bundle_result.evaluations)
            bundle_accuracy = self._accuracy(bundle_result.evaluations)
            bundle_delta = bundle_accuracy - baseline_accuracy
            if bundle_broken or bundle_schema or bundle_delta < min_accuracy_delta:
                candidate.rejection_reason = "FEWSHOT_BUNDLE_REGRESSION_OR_INSUFFICIENT_GAIN"
                self._record_rejection(report, candidate, bundle_delta, bundle_broken, bundle_schema, candidate.rejection_reason)
                candidate_pool.mark_tested(candidate_id=candidate.id, round_id=round_id, accuracy_delta=bundle_delta, accepted=False, rejection_reason=candidate.rejection_reason, broken_sample_ids=bundle_broken)
                continue

            candidate_report = replace(report)
            candidate_report.accepted = True
            candidate_report.reason = "ACCEPTED"
            candidate_report.operation_type = operation_type
            candidate_report.replaced_slot_index = replace_slot.get("slot_index") if replace_slot else None
            candidate_report.replaced_sample_id = replace_slot.get("source_sample_id") if replace_slot else None
            if operation_type == "REPLACE_SLOT":
                candidate_report.replacement_count = 1
            candidate_report.prompt_version_after_id = candidate_prompt.id
            candidate_report.fewshot_set_version_id = fewshot_set.id
            candidate_report.selected_candidate_id = candidate.id
            candidate_report.selected_sample_id = candidate.sample_id
            candidate_report.slot_count_after = self._slot_count(candidate_prompt)
            candidate_report.candidate_accuracy = candidate_accuracy
            candidate_report.accuracy_delta = delta
            candidate_report.bundle_accuracy = bundle_accuracy
            candidate_report.bundle_accuracy_delta = bundle_delta
            candidate_report.broken_sample_ids = broken
            candidate_report.schema_violation_sample_ids = schema_violations
            candidate_report.bundle_broken_sample_ids = bundle_broken
            candidate_report.bundle_schema_violation_sample_ids = bundle_schema
            if best_safe is None or bundle_delta > best_safe[0]:
                best_safe = (bundle_delta, candidate_prompt, candidate_report)

        if best_safe is not None:
            _, best_prompt, best_report = best_safe
            if best_report.selected_candidate_id:
                candidate_pool.mark_tested(
                    candidate_id=best_report.selected_candidate_id,
                    round_id=round_id,
                    accuracy_delta=best_report.bundle_accuracy_delta,
                    accepted=True,
                )
            return best_prompt, best_report, all_runs, all_evaluations

        report.failure_reason = "NO_SAFE_FEWSHOT_CANDIDATE"
        return prompt, report, all_runs, all_evaluations

    def _run_prompt(self, round_id: str, prompt: PromptVersion, samples: list[Sample], assets: dict[str, SampleAsset], ground_truths: dict[str, GroundTruth], contract: OutputSchemaContract, suffix: str, run_type: str):
        return PromptTestRunner(model_client=self.model_client, evaluator=self.evaluator, model_id=self.model_id, model_config=self.model_config).run(
            round_id=round_id,
            run_type=run_type,
            prompt=prompt,
            samples=samples,
            assets=assets,
            ground_truths=ground_truths,
            contract=contract,
            run_id_suffix=suffix,
        )

    def _record_rejection(self, report: FewShotOptimizationReport, candidate: FewShotCandidate, delta: float, broken: list[str], schema_violations: list[str], reason: str) -> None:
        report.rejected_candidates.append(
            {
                "candidate_id": candidate.id,
                "sample_id": candidate.sample_id,
                "accuracy_delta": delta,
                "broken_sample_ids": broken,
                "schema_violation_sample_ids": schema_violations,
                "reason": reason,
            }
        )

    def _mine_candidates(self, base_evaluations: list[EvaluationRecord], sample_states: dict[str, SampleState]) -> list[FewShotCandidate]:
        candidates: list[FewShotCandidate] = []
        for evaluation in base_evaluations:
            if evaluation.overall_status == "correct":
                continue
            state = sample_states.get(evaluation.sample_id, SampleState(sample_id=evaluation.sample_id))
            score = 1.0 + state.difficulty_ema + 0.1 * state.consecutive_wrong_count
            candidates.append(FewShotCandidate(id=f"fewshot_candidate_{evaluation.sample_id}", sample_id=evaluation.sample_id, candidate_score=score))
        return sorted(candidates, key=lambda candidate: candidate.candidate_score, reverse=True)

    def _dedupe_candidates(self, candidates: list[FewShotCandidate]) -> list[FewShotCandidate]:
        seen = set()
        result = []
        for candidate in sorted(candidates, key=lambda item: item.candidate_score, reverse=True):
            if candidate.id in seen:
                continue
            seen.add(candidate.id)
            result.append(candidate)
        return result

    def _generate_example(self, candidate: FewShotCandidate, sample: Sample, ground_truth: GroundTruth, contract: OutputSchemaContract) -> FewShotExample:
        final_output = self._schema_complete_output(ground_truth.value, ground_truth.primary_answer, contract)
        schema_result = self.evaluator.validator.validate(final_output, contract.schema)
        primary_fields = contract.primary_answer_fields if contract.primary_answer_fields else ["result"]
        primary_matches = all(final_output.get(field) == ground_truth.value.get(field, ground_truth.primary_answer) for field in primary_fields)
        reasoning_text = sample.metadata.get("fewshot_reasoning") or self._generate_reasoning_text(sample, ground_truth, final_output)
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
            status="validated" if schema_result.valid and primary_matches and reasoning_text.strip() else "rejected",
        )

    def _generate_reasoning_text(self, sample: Sample, ground_truth: GroundTruth, final_output: dict[str, Any]) -> str:
        if self.reasoning_model_client is None:
            return "根据图像和上下文证据，按输出 schema 给出与 ground truth 一致的审核结论。"
        response = self.reasoning_model_client.complete(
            [
                {"role": "system", "content": "Generate a concise few-shot reasoning example without changing the output schema."},
                {
                    "role": "user",
                    "content": json.dumps({
                        "sample_id": sample.id,
                        "ground_truth": ground_truth.value,
                        "final_output": final_output,
                        "text_context": sample.text_context,
                        "mock_output": sample.metadata.get("mock_fewshot_reasoning"),
                    }, ensure_ascii=False),
                },
            ],
            model_config=self.reasoning_model_config,
        )
        text = response.raw_output.strip()
        if not text or "新增字段" in text or "change schema" in text.lower():
            return "根据图像和上下文证据，按输出 schema 给出与 ground truth 一致的审核结论。"
        return text

    def _candidate_prompt(self, prompt: PromptVersion, example: FewShotExample, *, new_version: int, max_slots: int, replace_slot: dict[str, Any] | None = None) -> tuple[PromptVersion, FewShotSetVersion]:
        existing = prompt.prompt_ir.section_by_id(self.SECTION_ID)
        existing_content = existing.content.strip() if existing is not None else ""
        slots = self._parse_slots(prompt)
        if replace_slot is None:
            slot_index = len(slots) + 1
            example_block = self._render_example(example, slot_index=slot_index)
            new_content = "\n\n".join(chunk for chunk in [existing_content, example_block] if chunk)
        else:
            slot_index = int(replace_slot["slot_index"])
            new_block = self._render_example(example, slot_index=slot_index)
            new_content = self._replace_slot_content(existing_content, slot_index, new_block)
        if existing is None:
            sections = [
                *prompt.prompt_ir.sections,
                PromptSection(id=self.SECTION_ID, type="few_shot_examples", content=new_content, name="Few-shot examples", scope="framework", priority="high", compressibility="low", mutability="limited"),
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
            slot_count=min(max_slots, len(self._parse_slots_from_content(new_content))),
            slots=[{"slot_index": slot_index, "example_id": example.id, "source_sample_id": example.source_sample_id}],
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

    def _replacement_slot(self, slots: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not slots:
            return None
        valid_slots = []
        for item in slots:
            try:
                slot_index = int(item.get("slot_index", 0))
                valid_slots.append((slot_index, item))
            except (ValueError, TypeError):
                continue
        if not valid_slots:
            return None
        return sorted(valid_slots, key=lambda x: x[0])[0][1]

    def _parse_slots(self, prompt: PromptVersion) -> list[dict[str, Any]]:
        section = prompt.prompt_ir.section_by_id(self.SECTION_ID)
        return self._parse_slots_from_content(section.content if section is not None else "")

    def _parse_slots_from_content(self, content: str) -> list[dict[str, Any]]:
        slots: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in content.splitlines():
            if line.startswith("FEW_SHOT_SLOT:"):
                if current is not None:
                    slots.append(current)
                current = {"slot_index": int(line.split(":", 1)[1]), "source_sample_id": None}
            elif line.startswith("FEW_SHOT_SAMPLE:") and current is not None:
                current["source_sample_id"] = line.split(":", 1)[1]
        if current is not None:
            slots.append(current)
        return slots

    def _replace_slot_content(self, content: str, slot_index: int, replacement_block: str) -> str:
        blocks = [block for block in content.split("\n\n") if block.strip()]
        replaced = False
        for idx, block in enumerate(blocks):
            if f"FEW_SHOT_SLOT:{slot_index}" in block.splitlines():
                blocks[idx] = replacement_block
                replaced = True
                break
        if not replaced:
            blocks.append(replacement_block)
        return "\n\n".join(blocks)

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
        return len(self._parse_slots(prompt))

    def _regressions(self, baseline_by_sample: dict[str, EvaluationRecord], candidate_evaluations: list[EvaluationRecord]) -> tuple[list[str], list[str]]:
        broken: list[str] = []
        schema_violations: list[str] = []
        for candidate in candidate_evaluations:
            baseline = baseline_by_sample.get(candidate.sample_id)
            if baseline is None:
                continue
            if candidate.overall_status in {"parse_error", "schema_error"} or not candidate.schema_valid:
                schema_violations.append(candidate.sample_id)
            if baseline.overall_status == "correct" and candidate.overall_status != "correct":
                broken.append(candidate.sample_id)
        return broken, schema_violations

    def _accuracy(self, evaluations: list[EvaluationRecord]) -> float:
        if not evaluations:
            return 0.0
        return sum(1 for evaluation in evaluations if evaluation.overall_status == "correct") / len(evaluations)
