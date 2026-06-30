from __future__ import annotations

import base64
import io

import pytest

from mmap_optimizer.model.image_payload import (
    encode_local_image_as_data_url,
    normalize_image_resize,
)


def test_normalize_image_resize_accepts_ratio_and_integer_limit():
    assert normalize_image_resize(0.5) == 0.5
    assert normalize_image_resize(1024) == 1024
    assert normalize_image_resize(1024.0) == 1024


@pytest.mark.parametrize("value", [0, -1, 1.25, "0.5", False])
def test_normalize_image_resize_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="image_resize"):
        normalize_image_resize(value)


def test_encode_local_image_as_data_url_requires_pillow_for_resize(tmp_path, monkeypatch):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"fake")

    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PIL":
            raise ImportError("missing pillow")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(RuntimeError, match="Pillow"):
        encode_local_image_as_data_url(str(image_path), "image/png", image_resize=0.5)


def test_encode_local_image_as_data_url_resizes_when_pillow_available(tmp_path):
    pil = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "sample.png"
    image = pil.new("RGB", (20, 10), color="red")
    image.save(image_path, format="PNG")

    data_url = encode_local_image_as_data_url(
        str(image_path),
        "image/png",
        image_resize=0.5,
    )

    encoded = data_url.split(",", 1)[1]
    resized = pil.open(io.BytesIO(base64.b64decode(encoded)))
    assert resized.size == (10, 5)


def test_encode_local_image_as_data_url_integer_limit_only_shrinks_large_images(tmp_path):
    pil = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "sample.png"
    image = pil.new("RGB", (200, 100), color="blue")
    image.save(image_path, format="PNG")

    data_url = encode_local_image_as_data_url(
        str(image_path),
        "image/png",
        image_resize=50,
    )

    encoded = data_url.split(",", 1)[1]
    resized = pil.open(io.BytesIO(base64.b64decode(encoded)))
    assert resized.size == (50, 25)
