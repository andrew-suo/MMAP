from __future__ import annotations

import json

from mmap_optimizer.orchestration import OptimizerLoop, PromptSnapshot


def load_checkpoint(run_dir):
    return json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))


def test_one_round_writes_checkpoint(tmp_path):
    loop = OptimizerLoop(
        tmp_path,
        rounds=1,
        fewshot_pool_path="fewshots.jsonl",
        sample_states=[{"sample_id": "s1", "state": "done"}],
        metrics_summary={"accuracy": 0.8},
    )

    checkpoint = loop.run()

    payload = load_checkpoint(tmp_path)
    assert checkpoint.round_index == 0
    assert payload["round_index"] == 0
    assert payload["fewshot_pool_path"] == "fewshots.jsonl"
    assert payload["sample_states"] == [{"sample_id": "s1", "state": "done"}]
    assert payload["metrics_summary"] == {"accuracy": 0.8}
    assert payload["active_prompts"]["extraction"]["version"] == 2
    assert payload["active_prompts"]["extraction"]["rendered_hash"]
    assert (tmp_path / "round_000000" / "prompts").is_dir()


def test_resume_continues_round_id_and_prompt_versions(tmp_path):
    OptimizerLoop(tmp_path, rounds=1).run()

    checkpoint = OptimizerLoop(tmp_path, rounds=1, resume=True).run()

    payload = load_checkpoint(tmp_path)
    assert checkpoint.round_index == 1
    assert payload["round_index"] == 1
    assert payload["active_prompts"]["extraction"]["version"] == 3
    assert payload["active_prompts"]["analysis"]["version"] == 3
    assert (tmp_path / "round_000001" / "prompts").is_dir()


def test_rollback_restores_active_prompt_to_snapshot(tmp_path):
    OptimizerLoop(tmp_path, rounds=1).run()
    snapshot = PromptSnapshot.load(
        tmp_path / "round_000000" / "prompts" / "round_000000_extraction_before_v000001.json"
    )

    loop = OptimizerLoop(
        tmp_path,
        rounds=0,
        resume=True,
        rollback_to_snapshot_id=snapshot.snapshot_id,
    )

    active = loop.active_prompts["extraction"]
    assert active.version == snapshot.version
    assert active.rendered == snapshot.rendered
    assert active.snapshot_id == snapshot.snapshot_id
