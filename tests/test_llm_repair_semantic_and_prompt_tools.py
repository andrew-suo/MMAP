import json

from mmap_optimizer.analysis.parser import parse_analysis_output_with_repair
from mmap_optimizer.compression.semantic import SemanticCompressionEngine
from mmap_optimizer.core.config import optimizer_config_from_mapping
from mmap_optimizer.model.client import ModelResponse
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.semantic import SemanticPatchProcessor
from mmap_optimizer.prompt.ir import PromptIR, PromptSection
from mmap_optimizer.prompt.refactor import fix_ordered_list_numbering
from mmap_optimizer.prompt.standardizer import normalize_markdown_spacing, unique_heading_titles


class QueueClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def complete(self, messages, model_config=None, response_format=None):
        self.calls.append({"messages": messages, "model_config": model_config, "response_format": response_format})
        return ModelResponse(raw_output=self.outputs.pop(0))

    def complete_multimodal(self, messages, assets, model_config=None, response_format=None):
        return self.complete(messages, model_config, response_format)


def prompt_ir():
    return PromptIR(
        id="ir",
        prompt_type="extraction",
        version=1,
        output_schema_contract_id="contract",
        sections=[PromptSection(id="rules", type="rules", content="rule text")],
    )


def patch(pid="p1", text="检查标签缺失"):
    return Patch(
        id=pid,
        type="prompt_patch",
        status="candidate",
        target_prompt_type="extraction",
        base_version_id="v1",
        section_id="rules",
        operation_type="ADD_RULE",
        operation_mode="append",
        intent_name="intent",
        intent_description="intent",
        patch_text=text,
        rationale="rationale",
        source_sample_ids=["s1"],
    )


def valid_analysis_json():
    return json.dumps(
        {
            "judgement": {"is_correct": False},
            "confirmed_facts": [],
            "hypothesized_error_causes": [],
            "prompt_section_attribution": [],
            "patch_candidates": [],
        }
    )


def test_parse_analysis_output_uses_llm_json_repair_fallback():
    client = QueueClient([valid_analysis_json()])

    result = parse_analysis_output_with_repair("not json", repair_client=client, enable_llm_repair=True)

    assert result.parse_success is True
    assert result.repaired is True
    assert "LLM_JSON_REPAIR_ATTEMPT_1" in result.repair_actions
    assert len(client.calls) == 1


def test_semantic_patch_processor_falls_back_on_invalid_json():
    client = QueueClient(["not json"])
    patches = [patch()]

    result = SemanticPatchProcessor(client).merge(patches, prompt_ir())

    assert result == patches


def test_semantic_patch_processor_accepts_json_patch_payload():
    client = QueueClient([json.dumps([{**patch().__dict__, "patch_text": "合并后的规则"}], ensure_ascii=False)])

    result = SemanticPatchProcessor(client).merge([patch()], prompt_ir())

    assert result[0].patch_text == "合并后的规则"


def test_semantic_compression_prunes_and_validates():
    client = QueueClient(["保留核心规则", json.dumps({"valid": True, "reason": "equivalent"})])

    result = SemanticCompressionEngine(client).prune_section(section_header="rules", section_content="保留核心规则\n\n保留核心规则")

    assert result.semantic_valid is True
    assert result.content == "保留核心规则"
    assert result.reason == "equivalent"


def test_prompt_refactor_and_standardizer_helpers_are_lossless_format_tools():
    assert fix_ordered_list_numbering("1. A\n3. B") == "1. A\n2. B"
    assert normalize_markdown_spacing("## A\ntext\n## B\nmore") == "## A\n\ntext\n\n## B\n\nmore"
    assert unique_heading_titles("## A\ntext\n## A") == "## A\ntext\n## A (2)"


def test_optimizer_config_reads_llm_feature_flags():
    config = optimizer_config_from_mapping(
        {
            "analysis": {"json_repair_enabled": True, "json_repair_max_attempts": 2},
            "patch_merge": {"semantic_enabled": True, "root_audit_enabled": True},
            "compression": {"llm_enabled": True},
        }
    )

    assert config.analysis_json_repair_enabled is True
    assert config.analysis_json_repair_max_attempts == 2
    assert config.patch_semantic_merge_enabled is True
    assert config.patch_root_audit_enabled is True
    assert config.llm_compression_enabled is True
