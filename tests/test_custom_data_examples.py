from __future__ import annotations

import json
from pathlib import Path

from mmap_optimizer.core.config import load_config
from mmap_optimizer.data.dataset_loader import DatasetLoader, load_sample_specs


REPO_ROOT = Path(__file__).resolve().parent.parent
CUSTOM_CONFIG = REPO_ROOT / "configs" / "custom_data.example.yaml"
CUSTOM_SAMPLES = REPO_ROOT / "data" / "custom_samples.example.jsonl"
CUSTOM_GROUND_TRUTH = REPO_ROOT / "data" / "custom_ground_truth.example.jsonl"


def test_custom_data_example_config_loads():
    config = load_config(CUSTOM_CONFIG)

    assert config.run.use_mock is True
    assert config.dataset.path == "data/custom_samples.example.jsonl"
    assert config.dataset.image_root == "data/custom_images"
    assert config.dataset.ground_truth_path == "data/custom_ground_truth.example.jsonl"


def test_custom_data_example_samples_cover_text_single_and_multi_image():
    specs = load_sample_specs(CUSTOM_SAMPLES)

    assert [spec.id for spec in specs] == ["text_001", "image_001", "multi_001"]
    assert specs[0].assets == []
    assert len(specs[1].assets) == 1
    assert [asset.id for asset in specs[2].assets] == [
        "multi_001_front",
        "multi_001_back",
        "multi_001_detail",
    ]


def test_custom_data_example_loader_applies_image_root_and_external_ground_truth(tmp_path):
    image_root = tmp_path / "custom_images"
    sample_set = DatasetLoader(
        dataset_path=CUSTOM_SAMPLES,
        image_root=image_root,
    ).load_with_ground_truth(CUSTOM_GROUND_TRUTH)

    multi = sample_set.specs["multi_001"]
    assert [asset.local_path for asset in multi.assets] == [
        str(image_root / "images" / "multi_001_front.png"),
        str(image_root / "images" / "multi_001_back.png"),
        str(image_root / "images" / "multi_001_detail.png"),
    ]
    assert multi.ground_truth == {"result": "NG", "product_id": "M001", "defect": "scratch"}


def test_custom_data_example_external_ground_truth_can_override_values(tmp_path):
    gt_path = tmp_path / "override_gt.jsonl"
    gt_path.write_text(
        "\n".join(
            [
                json.dumps({"sample_id": "text_001", "value": {"result": "OVERRIDDEN"}}, ensure_ascii=False),
                json.dumps({"sample_id": "multi_001", "value": {"result": "OK", "product_id": "M001"}}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    sample_set = DatasetLoader(dataset_path=CUSTOM_SAMPLES).load_with_ground_truth(gt_path)

    assert sample_set.specs["text_001"].ground_truth == {"result": "OVERRIDDEN"}
    assert sample_set.specs["multi_001"].ground_truth == {"result": "OK", "product_id": "M001"}
