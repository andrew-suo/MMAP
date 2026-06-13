from __future__ import annotations

from dataclasses import dataclass

from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset
from mmap_optimizer.evaluation.evaluator import Evaluator
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.testing.prompt_test_runner import PromptTestRunner
from mmap_optimizer.model.client import ModelClient


@dataclass
class PromptABTestResult:
    baseline_prompt_version_id: str
    candidate_prompt_version_id: str
    sample_ids: list[str]
    baseline_accuracy: float
    candidate_accuracy: float
    accuracy_delta: float
    promoted: bool


def run_prompt_ab_test(
    *,
    model_client: ModelClient,
    evaluator: Evaluator,
    baseline_prompt: PromptVersion,
    candidate_prompt: PromptVersion,
    samples: list[Sample],
    assets: dict[str, SampleAsset],
    ground_truths: dict[str, GroundTruth],
    contract: OutputSchemaContract,
    min_accuracy_delta: float = 0.0,
    max_workers: int = 1,
) -> PromptABTestResult:
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, max_workers=max_workers)
    baseline = runner.run(
        round_id="ab_test",
        run_type="ab_baseline",
        prompt=baseline_prompt,
        samples=samples,
        assets=assets,
        ground_truths=ground_truths,
        contract=contract,
    )
    candidate = runner.run(
        round_id="ab_test",
        run_type="ab_candidate",
        prompt=candidate_prompt,
        samples=samples,
        assets=assets,
        ground_truths=ground_truths,
        contract=contract,
    )
    baseline_accuracy = _accuracy(baseline.evaluations)
    candidate_accuracy = _accuracy(candidate.evaluations)
    delta = candidate_accuracy - baseline_accuracy
    return PromptABTestResult(
        baseline_prompt_version_id=baseline_prompt.id,
        candidate_prompt_version_id=candidate_prompt.id,
        sample_ids=[sample.id for sample in samples],
        baseline_accuracy=baseline_accuracy,
        candidate_accuracy=candidate_accuracy,
        accuracy_delta=delta,
        promoted=delta >= min_accuracy_delta and candidate_accuracy >= baseline_accuracy,
    )


def _accuracy(evaluations) -> float:
    if not evaluations:
        return 0.0
    return sum(1 for evaluation in evaluations if evaluation.overall_status == "correct") / len(evaluations)
