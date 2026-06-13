from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.dataset.sample import GroundTruth
from mmap_optimizer.evaluation.evaluator import Evaluator
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.initializer import initialize_prompt_version


def contract():
    return OutputSchemaContract(
        id="schema_v1",
        prompt_type=PromptType.EXTRACTION,
        version=1,
        primary_answer_fields=["result"],
        schema={
            "type": "object",
            "required": ["result", "confidence", "evidence", "used_prompt_sections"],
            "properties": {
                "result": {"type": "string", "enum": ["OK", "NG", "UNCERTAIN"]},
                "confidence": {"type": "number"},
                "evidence": {"type": "array"},
                "used_prompt_sections": {"type": "array"},
            },
        },
    )


def test_initializer_freezes_output_schema_and_keeps_legacy_prompt():
    version = initialize_prompt_version("原始提示词", PromptType.EXTRACTION, contract())
    output = version.prompt_ir.section_by_id("output_schema")
    legacy = version.prompt_ir.section_by_id("legacy_unmapped")

    assert output is not None
    assert output.mutability == "frozen"
    assert output.compressibility == "none"
    assert legacy is not None
    assert legacy.content == "原始提示词"
    assert '<SECTION id="output_schema"' in version.render().text


def test_evaluator_requires_schema_validity_for_correctness():
    gt = GroundTruth(id="gt1", sample_id="s1", value={"result": "OK"}, primary_answer="OK")
    evaluator = Evaluator()

    valid = evaluator.evaluate(
        round_id="r1",
        run_id="run1",
        sample_id="s1",
        raw_output='{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
        ground_truth=gt,
        contract=contract(),
    )
    invalid_schema = evaluator.evaluate(
        round_id="r1",
        run_id="run2",
        sample_id="s1",
        raw_output='{"result":"OK"}',
        ground_truth=gt,
        contract=contract(),
    )

    assert valid.overall_status == "correct"
    assert invalid_schema.overall_status == "schema_error"
    assert not invalid_schema.primary_answer_correct
