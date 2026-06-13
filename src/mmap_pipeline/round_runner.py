"""Round execution and checkpoint writing."""

from __future__ import annotations

from .checkpoint import CheckpointState, CheckpointStore


class RoundRunner:
    """Run optimization rounds and checkpoint state when each round completes."""

    def __init__(self, state: CheckpointState, checkpoint_store: CheckpointStore) -> None:
        self.state = state
        self.checkpoint_store = checkpoint_store

    def next_round_id(self) -> int:
        """Return the next monotonically increasing round id."""

        if not self.state.completed_round_ids:
            return 1
        return max(self.state.completed_round_ids) + 1

    def run_next_round(self) -> CheckpointState:
        """Run one round and write a checkpoint before returning updated state."""

        round_id = self.next_round_id()
        if round_id in self.state.completed_round_ids:
            raise ValueError(f"round id {round_id} was already completed")

        for sample_id, sample_state in self.state.sample_states.items():
            sample_state["status"] = "completed"
            sample_state["last_completed_round_id"] = round_id

        self.state.completed_round_ids.append(round_id)
        self.state.latest_metrics = {
            "round_id": round_id,
            "completed_samples": len(self.state.sample_states),
        }
        self.state.active_extraction_prompt_version_id += 1
        self.state.active_analysis_prompt_version_id += 1
        self.checkpoint_store.save(self.state)
        return self.state
