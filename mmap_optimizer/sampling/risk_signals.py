"""Sample-level and section-level risk signals for risk-aware sampling.

This module exposes lightweight helpers for computing per-sample risk signals,
updating exponential-moving-average statistics, ranking samples deterministically
by risk, and selecting risk-weighted batches.  All helpers are pure functions and
small dataclasses — they do **not** modify the default optimizer loop behavior,
do not drive compression, merging, or prompt schema changes, and remain fully
testable on isolated inputs.

Design notes:

* ``risk_score`` is a bounded ``[0, 1]`` value derived from ``SampleState`` fields
  already produced by the optimizer: ``difficulty_ema``, ``fragility_score``,
  ``consecutive_wrong_count``, ``toxic_trigger`` and ``historical_fixed``.
* ``risk_level`` is a deterministic bucketing into ``low`` / ``medium`` / ``high``.
* Ranking is (1) risk_score descending, (2) last_selected_round ascending with
  "never selected" prioritized, (3) sample_id ASCII for final tie breaking.
* The section-level ``compute_section_risk_score`` mirrors PR #3's formula but
  is kept as a lightweight helper — it composes with the existing
  :mod:`mmap_optimizer.metrics.section_deltas` output instead of introducing a
  new schema.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from mmap_optimizer.dataset.sample import Sample, SampleState


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RISK_SCORE_FLOOR = 0.0
RISK_SCORE_CEIL = 1.0

RISK_LEVEL_LOW = "low"
RISK_LEVEL_MEDIUM = "medium"
RISK_LEVEL_HIGH = "high"

RISK_LEVEL_LOW_THRESHOLD = 0.33
RISK_LEVEL_HIGH_THRESHOLD = 0.66

DEFAULT_EMA_ALPHA_DIFFICULTY = 0.35
DEFAULT_EMA_ALPHA_FRAGILITY = 0.25

RISK_ARTIFACT_FILENAME = "sample_risk_signals.json"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SampleRiskSignal:
    """Risk signal for a single sample.

    ``risk_score`` is always clamped to ``[0, 1]``.  ``risk_level`` is the
    deterministic bucket derived from the score.  ``reasons`` documents which
    input components pushed the score up so callers can inspect the decision
    later.
    """

    sample_id: str
    risk_score: float = 0.0
    risk_level: str = RISK_LEVEL_LOW
    difficulty_ema: float = 0.0
    fragility_score: float = 0.0
    last_selected_round: int | None = None
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "difficulty_ema": self.difficulty_ema,
            "fragility_score": self.fragility_score,
            "last_selected_round": self.last_selected_round,
            "reasons": list(self.reasons),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Core risk scoring
# ---------------------------------------------------------------------------


def _clamp(value: float, low: float = RISK_SCORE_FLOOR, high: float = RISK_SCORE_CEIL) -> float:
    return max(low, min(high, float(value)))


def _state_field(state: Any, field_name: str, default: Any = 0) -> Any:
    """Extract a field from a SampleState object or a dict."""

    if isinstance(state, Mapping):
        value = state.get(field_name, default)
        return default if value is None else value
    return getattr(state, field_name, default) or default


def compute_sample_risk_score(state: SampleState | Mapping[str, Any]) -> tuple[float, list[str]]:
    """Return ``(risk_score, reasons)`` from a ``SampleState``.

    ``risk_score`` is always in ``[0, 1]``.  ``reasons`` lists the human
    readable components that contributed to an elevated signal.
    """

    difficulty_ema = float(_state_field(state, "difficulty_ema", 0.0))
    fragility_score = float(_state_field(state, "fragility_score", 0.0))
    consecutive_wrong = int(_state_field(state, "consecutive_wrong_count", 0))
    toxic_trigger = bool(_state_field(state, "toxic_trigger", False))
    historical_fixed = bool(_state_field(state, "historical_fixed", False))

    reasons: list[str] = []
    components: list[tuple[str, float]] = []

    components.append(("difficulty_ema", 0.4 * _clamp(difficulty_ema)))
    if difficulty_ema >= 0.5:
        reasons.append("high_difficulty_ema")

    components.append(("fragility_score", 0.3 * _clamp(fragility_score)))
    if fragility_score >= 0.5:
        reasons.append("high_fragility_score")

    wrong_component = 0.2 * _clamp(min(consecutive_wrong / 10.0, 1.0))
    components.append(("consecutive_wrong", wrong_component))
    if consecutive_wrong >= 3:
        reasons.append("consecutive_wrong_responses")

    toxic_component = 0.1 * (1.0 if toxic_trigger else 0.0)
    components.append(("toxic_trigger", toxic_component))
    if toxic_trigger:
        reasons.append("toxic_trigger")

    historical_component = 0.05 * (1.0 if historical_fixed else 0.0)
    components.append(("historical_fixed", historical_component))
    if historical_fixed:
        reasons.append("historical_fixed_sample")

    raw_score = sum(value for _, value in components)
    risk_score = _clamp(raw_score)
    return risk_score, reasons


def compute_sample_risk_level(risk_score: float) -> str:
    """Return the deterministic risk level bucket."""

    score = _clamp(risk_score)
    if score >= RISK_LEVEL_HIGH_THRESHOLD:
        return RISK_LEVEL_HIGH
    if score >= RISK_LEVEL_LOW_THRESHOLD:
        return RISK_LEVEL_MEDIUM
    return RISK_LEVEL_LOW


def build_sample_risk_signal(
    sample: Sample | Mapping[str, Any],
    sample_state: SampleState | Mapping[str, Any],
    *,
    section_risk_scores: Mapping[str, float] | None = None,
) -> SampleRiskSignal:
    """Build a :class:`SampleRiskSignal` from a sample + ``SampleState``.

    Optionally accepts a ``section_risk_scores`` mapping that lets sections
    identified on the sample's ``metadata`` nudge the risk score slightly —
    the nudge is capped to a small bonus so the sample-level signal remains
    dominant.
    """

    sample_id = (
        sample["id"] if isinstance(sample, Mapping) else getattr(sample, "id", "")
    )
    risk_score, reasons = compute_sample_risk_score(sample_state)

    difficulty_ema = float(_state_field(sample_state, "difficulty_ema", 0.0))
    fragility_score = float(_state_field(sample_state, "fragility_score", 0.0))
    last_selected_round = _state_field(sample_state, "last_selected_round", None)
    if last_selected_round is not None:
        last_selected_round = int(last_selected_round)

    section_bonus = 0.0
    section_reasons: list[str] = []
    if section_risk_scores:
        section_ids: list[str] = []
        metadata = sample.get("metadata", {}) if isinstance(sample, Mapping) else getattr(sample, "metadata", {})
        if isinstance(metadata, Mapping):
            candidate = metadata.get("section_ids") or metadata.get("sections")
            if isinstance(candidate, (list, tuple)):
                section_ids = [str(item) for item in candidate]
        for section_id in section_ids:
            if section_id in section_risk_scores:
                bonus = 0.05 * _clamp(float(section_risk_scores[section_id]))
                section_bonus = max(section_bonus, bonus)
                if section_risk_scores[section_id] >= 0.6:
                    section_reasons.append(f"high_risk_section:{section_id}")

    final_score = _clamp(risk_score + section_bonus)
    merged_reasons = list(reasons) + section_reasons
    level = compute_sample_risk_level(final_score)

    return SampleRiskSignal(
        sample_id=sample_id,
        risk_score=round(final_score, 6),
        risk_level=level,
        difficulty_ema=round(difficulty_ema, 6),
        fragility_score=round(fragility_score, 6),
        last_selected_round=last_selected_round,
        reasons=merged_reasons,
        metadata={
            "components": {
                name: round(value, 6) for name, value in [
                    ("difficulty_ema", 0.4 * difficulty_ema),
                    ("fragility_score", 0.3 * fragility_score),
                ]
            },
        },
    )


# ---------------------------------------------------------------------------
# Section risk score (mirrors PR #3's compute_section_risk formula)
# ---------------------------------------------------------------------------


def compute_section_risk_score(
    *,
    cited: float = 0.0,
    parasite: float = 0.0,
    accuracy: float = 1.0,
) -> float:
    """Return a bounded section risk score.

    Mirrors PR #3's ``compute_section_risk`` formula:
    ``0.4*cited + 0.4*parasite + 0.2*(1-accuracy)``.  Values are normalized
    to ``[0, 1]`` before combining, and the result is clamped to ``[0, 1]``.
    """

    cited_n = _clamp(float(cited))
    parasite_n = _clamp(float(parasite))
    accuracy_n = _clamp(float(accuracy))
    raw = (0.4 * cited_n) + (0.4 * parasite_n) + (0.2 * (1.0 - accuracy_n))
    return round(_clamp(raw), 6)


# ---------------------------------------------------------------------------
# EMA update helpers (pure functions; do not mutate SampleState)
# ---------------------------------------------------------------------------


def update_difficulty_ema(
    current_ema: float,
    is_correct: bool,
    *,
    alpha: float = DEFAULT_EMA_ALPHA_DIFFICULTY,
) -> float:
    """Return the new ``difficulty_ema`` after one evaluation.

    ``is_correct`` contributes ``0`` (easy), ``not is_correct`` contributes ``1``
    (hard).  ``alpha`` is the EMA smoothing factor; a larger value reacts faster.
    """

    contribution = 0.0 if bool(is_correct) else 1.0
    alpha_clamped = _clamp(float(alpha), 1e-3, 1.0)
    new_ema = (alpha_clamped * contribution) + ((1.0 - alpha_clamped) * float(current_ema))
    return round(_clamp(new_ema), 6)


def update_fragility_score(
    current_fragility: float,
    is_correct: bool,
    *,
    alpha: float = DEFAULT_EMA_ALPHA_FRAGILITY,
) -> float:
    """Return the new ``fragility_score`` after one evaluation.

    This is a directional EMA: wrong responses bump the signal up, correct
    responses gently pull it back down.  Asymmetric learning reflects that
    fragility is a "sticky" property — regressions matter more than recoveries.
    """

    current = float(current_fragility)
    alpha_clamped = _clamp(float(alpha), 1e-3, 1.0)
    if is_correct:
        # Gentle decay: multiply by (1 - alpha) toward 0.
        new_val = current * (1.0 - alpha_clamped)
    else:
        # Wrong response: push toward 1 with alpha.
        new_val = (alpha_clamped * 1.0) + ((1.0 - alpha_clamped) * current)
    return round(_clamp(new_val), 6)


# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------


def _last_selected_key(round_value: int | None) -> tuple[int, int]:
    """Never-selected samples come first; otherwise by ascending round."""

    if round_value is None:
        return (0, 0)
    return (1, int(round_value))


def rank_samples_by_risk(
    samples: Sequence[Sample | Mapping[str, Any]],
    sample_states: Mapping[str, SampleState | Mapping[str, Any]],
    *,
    section_risk_scores: Mapping[str, float] | None = None,
) -> list[SampleRiskSignal]:
    """Return samples ordered from highest risk to lowest.

    Primary key: ``risk_score`` descending.
    Secondary key: last_selected_round ascending, with "never selected" samples first.
    Tie breaker: ``sample_id`` ascending ASCII.

    The returned list is a fresh list of :class:`SampleRiskSignal` objects;
    the inputs are never mutated.
    """

    if not samples:
        return []

    signals: list[SampleRiskSignal] = []
    for sample in samples:
        sample_id = (
            sample["id"] if isinstance(sample, Mapping) else getattr(sample, "id", "")
        )
        state = sample_states.get(sample_id)
        if state is None:
            # Missing state → zero-risk default; still ranked deterministically.
            fallback_state: SampleState | dict[str, Any] = (
                SampleState(sample_id=sample_id) if not isinstance(sample, Mapping) else {"sample_id": sample_id}
            )
            signal = build_sample_risk_signal(sample, fallback_state, section_risk_scores=section_risk_scores)
        else:
            signal = build_sample_risk_signal(sample, state, section_risk_scores=section_risk_scores)
        signals.append(signal)

    signals.sort(
        key=lambda s: (
            -s.risk_score,
            _last_selected_key(s.last_selected_round),
            s.sample_id,
        )
    )
    return signals


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------


def select_risk_weighted_batch(
    samples: Sequence[Sample | Mapping[str, Any]],
    sample_states: Mapping[str, SampleState | Mapping[str, Any]],
    batch_size: int,
    *,
    seed: int = 0,
    section_risk_scores: Mapping[str, float] | None = None,
    exclude_sample_ids: set[str] | None = None,
) -> list[SampleRiskSignal]:
    """Select a batch prioritized by risk.

    The top ``batch_size`` samples from :func:`rank_samples_by_risk` are
    returned.  If there are fewer samples than ``batch_size`` the returned
    list has the same length as the input.  ``exclude_sample_ids`` lets
    callers drop samples (e.g. already selected in the same round).

    The function is deterministic for a given seed, but note that the
    default behavior of the optimizer loop is **not** modified — callers
    must explicitly opt in.
    """

    if batch_size <= 0:
        return []

    exclude = set(exclude_sample_ids or set())
    active = [
        s for s in samples
        if (s["id"] if isinstance(s, Mapping) else getattr(s, "id", "")) not in exclude
        and (_is_active(s) if _has_active_flag(s) else True)
    ]

    ranked = rank_samples_by_risk(active, sample_states, section_risk_scores=section_risk_scores)
    return ranked[: int(batch_size)]


def _has_active_flag(sample: Sample | Mapping[str, Any]) -> bool:
    if isinstance(sample, Mapping):
        return "active" in sample
    return hasattr(sample, "active")


def _is_active(sample: Sample | Mapping[str, Any]) -> bool:
    if isinstance(sample, Mapping):
        value = sample.get("active", True)
        return bool(value) if value is not None else True
    return bool(getattr(sample, "active", True))


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def sample_risk_signals_to_json(
    signals: Iterable[SampleRiskSignal],
    *,
    indent: int = 2,
    sort_keys: bool = True,
) -> str:
    """Return a JSON string representing the given risk signals."""

    payload = [signal.to_dict() for signal in signals]
    return json.dumps(payload, indent=indent, sort_keys=sort_keys)


def write_sample_risk_artifact(
    signals: Iterable[SampleRiskSignal],
    output_dir: Any,
    *,
    filename: str = RISK_ARTIFACT_FILENAME,
) -> str:
    """Write risk signals to ``<output_dir>/sample_risk_signals.json``."""

    from pathlib import Path

    path = Path(str(output_dir)) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sample_risk_signals_to_json(signals), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Convenience: compute signals for many samples at once
# ---------------------------------------------------------------------------


def compute_risk_signals(
    samples: Sequence[Sample | Mapping[str, Any]],
    sample_states: Mapping[str, SampleState | Mapping[str, Any]],
    *,
    section_risk_scores: Mapping[str, float] | None = None,
) -> list[SampleRiskSignal]:
    """Compute :class:`SampleRiskSignal` for every input sample.

    Returns the results in the same order as the input, without sorting — use
    :func:`rank_samples_by_risk` when you want a sorted list instead.
    """

    results: list[SampleRiskSignal] = []
    for sample in samples:
        sample_id = (
            sample["id"] if isinstance(sample, Mapping) else getattr(sample, "id", "")
        )
        state = sample_states.get(sample_id)
        if state is None:
            fallback_state: SampleState | dict[str, Any] = (
                SampleState(sample_id=sample_id) if not isinstance(sample, Mapping) else {"sample_id": sample_id}
            )
            results.append(build_sample_risk_signal(sample, fallback_state, section_risk_scores=section_risk_scores))
        else:
            results.append(build_sample_risk_signal(sample, state, section_risk_scores=section_risk_scores))
    return results
