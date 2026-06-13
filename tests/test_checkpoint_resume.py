from __future__ import annotations

from tests._compat import candidate_modules, find_symbol

CHECKPOINT_MODULES = candidate_modules(
    "mmap.checkpoint",
    "mmap.checkpoints",
    "mmap.runtime.checkpoint",
    "mmap_engine.checkpoint",
    "src.checkpoint",
)


def test_checkpoint_resume_restores_state_and_continues_from_next_step(tmp_path) -> None:
    manager_cls = find_symbol(CHECKPOINT_MODULES, "CheckpointManager", "CheckpointStore")
    manager = manager_cls(tmp_path)

    checkpoint_id = manager.save(run_id="run-1", step=2, state={"seen": ["a", "b"]})
    resumed = manager.resume(run_id="run-1")

    assert resumed["checkpoint_id"] == checkpoint_id
    assert resumed["step"] == 2
    assert resumed["next_step"] == 3
    assert resumed["state"] == {"seen": ["a", "b"]}


def test_rollback_restores_prior_checkpoint_without_deleting_newer_audit(tmp_path) -> None:
    manager_cls = find_symbol(CHECKPOINT_MODULES, "CheckpointManager", "CheckpointStore")
    manager = manager_cls(tmp_path)

    first = manager.save(run_id="run-2", step=1, state={"value": "old"})
    second = manager.save(run_id="run-2", step=2, state={"value": "new"})
    rolled_back = manager.rollback(run_id="run-2", checkpoint_id=first)

    assert rolled_back["state"] == {"value": "old"}
    history = manager.history("run-2")
    assert [item["checkpoint_id"] for item in history] == [first, second]
    assert history[-1]["state"] == {"value": "new"}
