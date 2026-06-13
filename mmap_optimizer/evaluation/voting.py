from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from mmap_optimizer.model.client import ModelClient


@dataclass
class EvalVoteResult:
    sample_id: str
    votes: list[str]
    majority_status: str
    confidence: float
    raw_judgements: list[str] = field(default_factory=list)
    model_ids: list[str] = field(default_factory=list)
    is_ground_truth_backed: bool = False


def run_eval_vote(
    *,
    model_client: ModelClient,
    sample_id: str,
    extraction_prompt: str,
    sample_payload: dict[str, Any],
    rounds: int = 3,
    model_id: str = "vote-model",
    model_config: dict[str, Any] | None = None,
) -> EvalVoteResult:
    votes: list[str] = []
    raw: list[str] = []
    for index in range(rounds):
        response = model_client.complete(
            [
                {"role": "system", "content": extraction_prompt},
                {"role": "user", "content": {**sample_payload, "sample_id": sample_id, "vote_round": index + 1}},
            ],
            model_config=model_config,
        )
        raw.append(response.raw_output)
        votes.append(_status_from_output(response.raw_output))
    counts = Counter(votes)
    majority_status, majority_count = counts.most_common(1)[0]
    return EvalVoteResult(
        sample_id=sample_id,
        votes=votes,
        majority_status=majority_status,
        confidence=majority_count / max(1, len(votes)),
        raw_judgements=raw,
        model_ids=[model_id] * len(votes),
        is_ground_truth_backed=False,
    )


def _status_from_output(raw_output: str) -> str:
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        return "invalid"
    if isinstance(parsed, dict):
        value = parsed.get("status") or parsed.get("result") or parsed.get("label")
        if value is not None:
            return str(value).strip().lower()
    return "invalid"
