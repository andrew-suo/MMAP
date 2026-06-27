"""Sample-centric optimization trajectory rendering."""

from __future__ import annotations

from ..data.sample import SampleOptimizationTrajectory, SamplePatchAttempt, SampleSet


class SampleTrajectoryRenderer:
    """Render compact sample optimization history for model prompts."""

    def __init__(self, trajectory_limit: int = 5, patch_limit: int = 8) -> None:
        self.trajectory_limit = trajectory_limit
        self.patch_limit = patch_limit

    def render(
        self,
        sample_set: SampleSet | None,
        sample_id: str | None,
        prompt_type: str | None = None,
    ) -> str:
        if sample_set is None or not sample_id:
            return ""
        state = sample_set.states.get(sample_id)
        if state is None:
            return ""

        trajectories = state.get_optimization_trajectory(
            prompt_type=prompt_type,
            limit=self.trajectory_limit,
        )
        if not trajectories:
            return ""

        lines = [
            "Use this sample-specific optimization trajectory as prior feedback. "
            "Do not treat it as visual evidence; use it to avoid repeated failed "
            "directions and to continue previously useful directions when relevant."
        ]
        for trajectory in trajectories:
            lines.extend(self._render_trajectory(trajectory))
        return "\n".join(lines)

    def _render_trajectory(self, trajectory: SampleOptimizationTrajectory) -> list[str]:
        line = (
            f"- iteration={trajectory.iteration}; prompt_type={trajectory.prompt_type}; "
            f"base={trajectory.base_status}; final={trajectory.final_status}; "
            f"transition={trajectory.sample_transition}"
        )
        lines = [line]
        if trajectory.base_raw_status not in {"", "unknown"} or trajectory.final_raw_status not in {"", "unknown"}:
            lines.append(
                "  raw_status="
                f"base={self._compact(trajectory.base_raw_status, 60)}; "
                f"final={self._compact(trajectory.final_raw_status, 60)}"
            )
        analysis_reason = trajectory.analysis_summary.get("error_reason")
        if analysis_reason:
            lines.append(f"  analysis_error_reason={self._compact(analysis_reason, 180)}")
        reflection_reason = trajectory.reflection_summary.get("error_reason")
        if reflection_reason:
            lines.append(f"  reflection_reason={self._compact(reflection_reason, 180)}")

        latest_attempts = trajectory.latest_patch_attempts(limit=self.patch_limit)
        for attempt in latest_attempts:
            lines.append(self._render_attempt(attempt))
        if not latest_attempts:
            reason = trajectory.metadata.get("no_patch_reason")
            if reason:
                lines.append(f"  no_patch_reason={self._compact(reason, 180)}")
        return lines

    def _render_attempt(self, attempt: SamplePatchAttempt) -> str:
        return (
            "  patch="
            f"{attempt.patch_id or attempt.attempt_id}; attempt={attempt.attempt_id}; "
            f"stage={attempt.stage}; stage_status={attempt.stage_status}; gen={attempt.generation_status}; "
            f"validation={attempt.validation_status}; merge={attempt.merge_status}; "
            f"decision={attempt.final_decision}; regression={attempt.regression_effect}; "
            f"toxicity={attempt.toxicity_status}; section={attempt.target_section_id}; "
            f"op={attempt.operation_type}; direction={self._compact(attempt.direction, 160)}; "
            f"content={self._compact(attempt.content, 220)}; "
            f"reason={self._compact(attempt.rejection_reason or attempt.rationale, 160)}"
        )

    def _compact(self, text: object, limit: int) -> str:
        value = " ".join(str(text or "").split())
        if len(value) <= limit:
            return value
        return value[: limit - 3] + "..."
