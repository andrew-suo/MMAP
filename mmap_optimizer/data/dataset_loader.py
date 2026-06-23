"""数据集加载器，负责从文件加载样本数据。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .sample import SampleAsset, SampleSpec, SampleSet, SampleState


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """读取 JSONL 文件。"""
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_sample_specs(path: str | Path) -> list[SampleSpec]:
    """从文件加载样本规格列表。"""
    rows = _read_jsonl(path)
    specs = []
    for row in rows:
        # 处理 assets
        assets = []
        if "assets" in row:
            for asset_data in row["assets"]:
                assets.append(SampleAsset(
                    id=asset_data.get("id", f"asset_{row.get('id', 'unknown')}"),
                    sample_id=row.get("id", "unknown"),
                    type=asset_data.get("type", "image"),
                    uri=asset_data.get("uri"),
                    local_path=asset_data.get("local_path"),
                    mime_type=asset_data.get("mime_type"),
                    metadata=asset_data.get("metadata", {}),
                ))

        # 处理 ground_truth
        ground_truth = row.get("ground_truth", {})
        if not ground_truth and "gt" in row:
            ground_truth = row["gt"]

        spec = SampleSpec(
            id=row.get("id", f"sample_{len(specs)}"),
            input=row.get("input", row.get("data", {})),
            ground_truth=ground_truth,
            assets=assets,
            metadata=row.get("metadata", {}),
            tags=row.get("tags", []),
            active=row.get("active", True),
        )
        specs.append(spec)
    return specs


def create_sample_set(specs: list[SampleSpec]) -> SampleSet:
    """创建样本集合并初始化状态。"""
    sample_set = SampleSet()
    for spec in specs:
        sample_set.add_spec(spec)
    return sample_set


class DatasetLoader:
    """数据集加载器，支持从配置加载样本数据。"""

    def __init__(
        self,
        dataset_path: str | Path,
        format: str = "jsonl",
        image_root: str | Path | None = None,
    ):
        self.dataset_path = Path(dataset_path)
        self.format = format
        self.image_root = Path(image_root) if image_root else None

    def load(self) -> SampleSet:
        """加载样本数据并返回样本集合。"""
        if self.format == "jsonl":
            specs = load_sample_specs(self.dataset_path)
        else:
            raise ValueError(f"Unsupported dataset format: {self.format}")

        # 如果有 image_root，更新资产的 local_path
        if self.image_root:
            for spec in specs:
                for asset in spec.assets:
                    if asset.uri and not asset.local_path:
                        # 尝试从 URI 推断本地路径
                        asset.local_path = str(self.image_root / Path(asset.uri).name)

        return create_sample_set(specs)

    def load_with_ground_truth(self, ground_truth_path: str | Path | None = None) -> SampleSet:
        """加载样本数据并合并 ground truth 文件。"""
        sample_set = self.load()

        if ground_truth_path:
            gt_rows = _read_jsonl(ground_truth_path)
            gt_map = {row.get("sample_id", row.get("id")): row.get("value", row.get("ground_truth", {})) for row in gt_rows}

            for sample_id, gt_value in gt_map.items():
                if sample_id in sample_set.specs:
                    sample_set.specs[sample_id].ground_truth = gt_value

        return sample_set
