from __future__ import annotations

import json
from enum import Enum
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable


def to_plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return to_plain(asdict(value))
    if isinstance(value, list):
        return [to_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: to_plain(v) for k, v in value.items()}
    return value


class JsonStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_json(self, relative_path: str | Path, value: Any) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(to_plain(value), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read_json(self, relative_path: str | Path) -> Any:
        return json.loads((self.root / relative_path).read_text(encoding="utf-8"))

    def append_jsonl(self, relative_path: str | Path, records: Iterable[Any]) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(to_plain(record), ensure_ascii=False) + "\n")
        return path
