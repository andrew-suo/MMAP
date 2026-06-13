from __future__ import annotations

import json

import pytest

from mmap_pipeline.optimizer import OptimizerLoop


def read_json(path):
    with path.open("r", encoding="utf-8") as json_file:
        return json.load(json_file)


def test_checkpoint_then_resume_continues_rounds_prompts_and_fewshot_pool(tmp_path):
    checkpoint_path = tmp_path / "checkpoint.json"
    fewshot_pool_path = tmp_path / "fewshot_pool.json"
    ignored_pool_path = tmp_path / "ignored_pool.json"

    first_loop = OptimizerLoop(
        checkpoint_path=checkpoint_path,
        fewshot_pool_path=fewshot_pool_path,
        sample_ids=["sample-a"],
    )
    first_state = first_loop.run(1)

    assert checkpoint_path.exists()
    assert fewshot_pool_path.exists()
    assert first_state.completed_round_ids == [1]
    assert first_state.active_extraction_prompt_version_id == 2
    assert first_state.active_analysis_prompt_version_id == 2

    resumed_loop = OptimizerLoop(
        checkpoint_path=checkpoint_path,
        fewshot_pool_path=ignored_pool_path,
        sample_ids=["new-sample-is-ignored-on-resume"],
        resume=True,
    )
    assert resumed_loop.state.fewshot_pool_path == str(fewshot_pool_path)

    second_state = resumed_loop.run(1)
    checkpoint_payload = read_json(checkpoint_path)

    assert second_state.completed_round_ids == [1, 2]
    assert len(second_state.completed_round_ids) == len(set(second_state.completed_round_ids))
    assert second_state.active_extraction_prompt_version_id == 3
    assert second_state.active_analysis_prompt_version_id == 3
    assert second_state.fewshot_pool_path == str(fewshot_pool_path)
    assert checkpoint_payload["completed_round_ids"] == [1, 2]
    assert checkpoint_payload["sample_states"]["sample-a"]["last_completed_round_id"] == 2
    assert not ignored_pool_path.exists()


def test_resume_requires_existing_checkpoint(tmp_path):
    with pytest.raises(FileNotFoundError):
        OptimizerLoop(checkpoint_path=tmp_path / "missing.json", resume=True)
