import json

from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.core.scenario import load_scenario
from mmap_optimizer.debug.logger import DebugEventLogger
from mmap_optimizer.evaluation.voting import run_eval_vote
from mmap_optimizer.metrics.section_contribution import build_section_contribution
from mmap_optimizer.model.client import ModelResponse
from mmap_optimizer.orchestration.executor import map_ordered
from mmap_optimizer.orchestration.run_state import RunState, RunStateStore
from mmap_optimizer.patch.applier import PatchApplier
from mmap_optimizer.patch.repair import PatchRepairEngine
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.validator import PatchValidator
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.health import check_prompt_health
from mmap_optimizer.prompt.initializer import initialize_prompt_version
from mmap_optimizer.prompt.ir import PromptIR, PromptSection
from mmap_optimizer.prompt.snapshot import load_prompt_snapshot, save_prompt_snapshot
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.storage.json_store import JsonStore


class QueueClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def complete(self, messages, model_config=None, response_format=None):
        return ModelResponse(raw_output=self.outputs.pop(0))

    def complete_multimodal(self, messages, assets, model_config=None, response_format=None):
        return self.complete(messages, model_config, response_format)


def prompt_version():
    ir = PromptIR(
        id="ir",
        prompt_type=PromptType.EXTRACTION,
        version=1,
        output_schema_contract_id="contract",
        sections=[PromptSection(id="rules", type="rules", content="A\nB"), PromptSection(id="output_schema", type="output_schema", content="{}", mutability="frozen", compressibility="none")],
        rendering_order=["rules", "output_schema"],
    )
    return PromptVersion(id="p1", prompt_type=PromptType.EXTRACTION, version=1, prompt_ir=ir, output_schema_contract_id="contract")


def patch(**kwargs):
    data = dict(
        id="patch1",
        type="prompt_patch",
        status="candidate",
        target_prompt_type="extraction",
        base_version_id="p1",
        section_id="rules",
        operation_type="ADD_RULE",
        operation_mode="append",
        intent_name="intent",
        intent_description="intent",
        patch_text="C",
        rationale="rationale",
        source_sample_ids=["s1"],
    )
    data.update(kwargs)
    return Patch(**data)


def test_text_level_patch_operations_and_validation():
    base = prompt_version()
    replace_patch = patch(operation_mode="replace_in_section", old_text="A", new_text="AA", patch_text="ignored")

    assert PatchValidator().validate(replace_patch, base.prompt_ir).valid
    updated = PatchApplier().apply(base, replace_patch, new_version=2)

    assert updated.prompt_ir.section_by_id("rules").content == "AA\nB"
    missing = patch(id="missing", operation_mode="insert_after", target_text="Z", patch_text="X")
    assert PatchValidator().validate(missing, base.prompt_ir).reason == "PATCH_LOCATOR_NOT_FOUND"


def test_section_contribution_channels():
    patches = [patch(status="accepted", fixed_sample_ids=["s1", "s2"]), patch(id="bad", status="rejected", broken_sample_ids=["s3"], rejection_reason="toxic")]

    result = build_section_contribution(patches=patches)

    assert result["rules"].active_count == 1
    assert result["rules"].parasite_count == 1
    assert result["rules"].fixed_count == 2


def test_eval_voting_majority_without_ground_truth():
    client = QueueClient(['{"status":"ok"}', '{"status":"ng"}', '{"status":"ok"}'])

    result = run_eval_vote(model_client=client, sample_id="s1", extraction_prompt="prompt", sample_payload={})

    assert result.majority_status == "ok"
    assert result.confidence == 2 / 3
    assert result.is_ground_truth_backed is False


def test_run_state_snapshot_debug_and_scenario(tmp_path):
    store = JsonStore(tmp_path)
    state_store = RunStateStore(store)
    state_store.save(RunState(run_id="run1", iteration=2, stage="analysis", completed_round_ids=["r1"]))
    assert state_store.load().stage == "analysis"

    snapshot = save_prompt_snapshot(store, prompt_version(), "snap1")
    assert load_prompt_snapshot(store, "snap1")["id"] == snapshot.id

    event = DebugEventLogger(store).log("parse_fail", "bad json", stage="analysis", round_id="r1")
    assert event.event_type == "parse_fail"

    scenario = tmp_path / "cabinet_cable"
    scenario.mkdir()
    (scenario / "optimizer.yaml").write_text("run_dir: runs\n", encoding="utf-8")
    loaded = load_scenario(scenario)
    assert loaded.id == "cabinet_cable"
    assert loaded.config_hash


def test_prompt_health_and_initializer_standardization():
    contract = OutputSchemaContract(id="c", prompt_type=PromptType.EXTRACTION, version=1, schema={"type": "object"}, primary_answer_fields=["answer"])
    version = initialize_prompt_version("## A\n1. first\n3. second\n## A", PromptType.EXTRACTION, contract, fix_numbering=True, normalize_spacing=True, unique_headings=True)
    legacy = version.prompt_ir.section_by_id("legacy_unmapped").content

    assert "2. second" in legacy
    assert "## A (2)" in legacy
    report = check_prompt_health(version.prompt_ir)
    assert report.ok


def test_patch_repair_engine_aligns_locator_without_payload_change():
    ir = PromptIR(id="ir", prompt_type="extraction", version=1, output_schema_contract_id="c", sections=[PromptSection(id="rules", type="rules", name="## Rules", content="检查标签缺失。")])
    result = PatchRepairEngine().repair_locator(patch={"target_section": "Rules", "old_text": "标签缺失问题", "new_text": "检查标签和铭牌缺失。"}, prompt_ir=ir, failure_info="old_text missing")

    assert result.repaired is True
    assert result.repaired_patch["section_id"] == "rules"
    assert result.repaired_patch["old_text"] == "检查标签缺失。"
    assert result.repaired_patch["new_text"] == "检查标签和铭牌缺失。"


def test_map_ordered_keeps_input_order_with_threads():
    assert map_ordered([3, 1, 2], lambda value: value * 2, max_workers=2) == [6, 2, 4]
