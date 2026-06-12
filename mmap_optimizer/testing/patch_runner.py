from __future__ import annotations

from dataclasses import dataclass

from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset
from mmap_optimizer.evaluation.evaluator import EvaluationRecord, Evaluator
from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.patch.applier import PatchApplier
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.orchestration.records import RunRecord
from .patch_tester import PatchTestResult, PatchTestSuite, summarize_patch_test
from .prompt_test_runner import PromptTestRunner


@dataclass
class PatchRunResult:
    temp_prompt: PromptVersion
    runs: list[RunRecord]
    evaluations: list[EvaluationRecord]
    test_result: PatchTestResult


class PatchTester:
    """Applies a patch to a temporary PromptVersion and evaluates real model outputs."""

    def __init__(self, *, model_client: ModelClient, evaluator: Evaluator, model_id: str = "mock-model"):
        self.prompt_runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, model_id=model_id)

    def test_individual(
        self,
        *,
        round_id: str,
        patch: Patch,
        base_prompt: PromptVersion,
        base_evaluations: list[EvaluationRecord],
        suite: PatchTestSuite,
        samples: list[Sample],
        assets: dict[str, SampleAsset],
        ground_truths: dict[str, GroundTruth],
        contract: OutputSchemaContract,
    ) -> PatchRunResult:
        temp_prompt = PatchApplier().apply(base_prompt, patch, new_version=base_prompt.version + 1)
        sample_by_id = {sample.id: sample for sample in samples}
        suite_samples = [sample_by_id[sample_id] for sample_id in suite.sample_ids if sample_id in sample_by_id]
        run_result = self.prompt_runner.run(
            round_id=round_id,
            run_type="patch_test_extraction",
            prompt=temp_prompt,
            samples=suite_samples,
            assets=assets,
            ground_truths=ground_truths,
            contract=contract,
            run_id_suffix=patch.id,
        )
        base_by_sample = {evaluation.sample_id: evaluation for evaluation in base_evaluations}
        ordered_base_evals = [base_by_sample[evaluation.sample_id] for evaluation in run_result.evaluations if evaluation.sample_id in base_by_sample]
        test_result = summarize_patch_test(round_id, patch.id, suite.id, ordered_base_evals, run_result.evaluations)
        return PatchRunResult(temp_prompt=temp_prompt, runs=run_result.runs, evaluations=run_result.evaluations, test_result=test_result)
