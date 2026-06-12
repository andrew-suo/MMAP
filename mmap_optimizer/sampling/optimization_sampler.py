from __future__ import annotations

import random

from mmap_optimizer.dataset.sample import Sample, SampleState


def select_optimization_batch(samples: list[Sample], sample_states: dict[str, SampleState], batch_size: int, *, round_index: int, seed: int = 0) -> list[Sample]:
    rng = random.Random(seed + round_index)
    active = [s for s in samples if s.active]
    active.sort(key=lambda s: (sample_states.get(s.id, SampleState(s.id)).difficulty_ema, rng.random()), reverse=True)
    hard_quota = max(1, int(batch_size * 0.25)) if active else 0
    selected = active[:hard_quota]
    remaining = active[hard_quota:]
    rng.shuffle(remaining)
    selected.extend(remaining[: max(0, batch_size - len(selected))])
    return selected
