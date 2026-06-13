from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.storage.json_store import JsonStore, to_plain


@dataclass
class PromptSnapshot:
    id: str
    prompt_version_id: str
    prompt_type: str
    version: int
    rendered_hash: str
    prompt_payload: dict[str, Any]


def save_prompt_snapshot(store: JsonStore, prompt: PromptVersion, snapshot_id: str) -> PromptSnapshot:
    rendered = prompt.render()
    prompt_type = getattr(prompt.prompt_type, "value", str(prompt.prompt_type))
    snapshot = PromptSnapshot(
        id=snapshot_id,
        prompt_version_id=prompt.id,
        prompt_type=prompt_type,
        version=prompt.version,
        rendered_hash=rendered.text_hash,
        prompt_payload=to_plain(prompt),
    )
    store.write_json(f"snapshots/{snapshot_id}.json", snapshot)
    return snapshot


def load_prompt_snapshot(store: JsonStore, snapshot_id: str) -> dict[str, Any]:
    return store.read_json(f"snapshots/{snapshot_id}.json")
