from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .sample import GroundTruth, Sample, SampleAsset, SampleState


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_samples(path: str | Path) -> list[Sample]:
    return [Sample(**row) for row in _read_jsonl(path)]


def load_ground_truths(path: str | Path) -> dict[str, GroundTruth]:
    rows = [GroundTruth(**row) for row in _read_jsonl(path)]
    return {row.id: row for row in rows}


def load_assets(path: str | Path) -> dict[str, SampleAsset]:
    rows = [SampleAsset(**row) for row in _read_jsonl(path)]
    return {row.id: row for row in rows}


def initial_sample_states(samples: list[Sample]) -> dict[str, SampleState]:
    return {sample.id: SampleState(sample_id=sample.id) for sample in samples}
