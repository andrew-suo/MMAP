from __future__ import annotations

from dataclasses import replace

from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.dataset.sample import GroundTruth, Sample
from mmap_optimizer.evaluation.evaluator import Evaluator
from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.prompt.ab_test import run_prompt_ab_test
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.initializer import initialize_prompt_version
from mmap_optimizer.prompt.self_check import self_check_prompt_text


def contract() -> OutputSchemaContract:
    schema = {
        "type": "object",
        "required": ["result", "confidence", "evidence", "used_prompt_sections"],
        "properties": {
            "result": {"type": "string"},
            "confidence": {"type": "number"},
            "evidence": {"type": "array"},
            "used_prompt_sections": {"type": "array"},
        },
        "x-primary-answer-fields": ["result"],
    }
    return OutputSchemaContract(id="contract", prompt_type=PromptType.EXTRACTION, version=1, schema=schema, primary_answer_fields=["result"])


def test_prompt_self_check_finds_schema_and_placeholder_issues():
    report = self_check_prompt_text(prompt_text="输出 {missing_placeholder}，不要修改输出格式，但允许新增输出字段", schema={"required": ["result"], "properties": {}})

    assert report.valid is False
    assert any(issue.code == "UNDECLARED_PLACEHOLDER" for issue in report.issues)
    assert any(issue.code == "SCHEMA_REQUIRED_WITHOUT_PROPERTY" for issue in report.issues)
    assert any(issue.code == "CONTRADICTORY_OUTPUT_FORMAT_RULE" for issue in report.issues)


def test_prompt_ab_test_promotes_non_regressing_candidate():
    c = contract()
    baseline = initialize_prompt_version("baseline", PromptType.EXTRACTION, c)
    candidate = initialize_prompt_version("candidate SPECIAL_RULE", PromptType.EXTRACTION, c)
    candidate = replace(candidate, id="candidate_prompt_v2")
    samples = [
        Sample(
            id="s1",
            ground_truth_id="gt1",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_prompt_outputs": [
                    {"contains": "SPECIAL_RULE", "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                ],
            },
        )
    ]
    result = run_prompt_ab_test(
        model_client=MockModelClient(),
        evaluator=Evaluator(),
        baseline_prompt=baseline,
        candidate_prompt=candidate,
        samples=samples,
        assets={},
        ground_truths={"gt1": GroundTruth(id="gt1", sample_id="s1", value={"result": "NG"}, primary_answer="NG")},
        contract=c,
        min_accuracy_delta=0.5,
    )

    assert result.baseline_accuracy == 0.0
    assert result.candidate_accuracy == 1.0
    assert result.promoted is True
