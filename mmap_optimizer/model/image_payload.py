from __future__ import annotations

import base64
import io
import mimetypes
from pathlib import Path
from typing import Any


def normalize_image_resize(image_resize: Any) -> float | int | None:
    """Normalize and validate the image resize config.

    Supported values:
    - None: disabled
    - 0 < float < 1: uniform scale ratio
    - int >= 1: max size for the longer edge
    - float >= 1 that is mathematically integral is coerced to int
    """
    if image_resize is None:
        return None
    if isinstance(image_resize, bool):
        raise ValueError("image_resize must be a float ratio or integer limit, not bool")
    if isinstance(image_resize, int):
        if image_resize < 1:
            raise ValueError("image_resize integer limit must be >= 1")
        return image_resize
    if isinstance(image_resize, float):
        if 0 < image_resize < 1:
            return image_resize
        if image_resize >= 1 and image_resize.is_integer():
            return int(image_resize)
        raise ValueError("image_resize float must satisfy 0 < value < 1, unless it is an integer-equivalent limit")
    raise ValueError("image_resize must be None, a float ratio, or an integer limit")


def encode_local_image_as_data_url(
    local_path: str,
    mime_type: str | None = None,
    image_resize: Any = None,
) -> str:
    """Read a local image, optionally resize it, and return a base64 data URL."""
    path = Path(local_path)
    inferred_mime = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    normalized_resize = normalize_image_resize(image_resize)
    image_bytes, output_mime = _load_image_bytes(
        path,
        inferred_mime=inferred_mime,
        image_resize=normalized_resize,
    )
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{output_mime};base64,{encoded}"


def _load_image_bytes(
    path: Path,
    *,
    inferred_mime: str,
    image_resize: float | int | None,
) -> tuple[bytes, str]:
    if image_resize is None:
        return path.read_bytes(), inferred_mime

    try:
        from PIL import Image  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "image_resize requires Pillow to be installed"
        ) from exc

    with Image.open(path) as image:
        original_size = image.size
        target_size = _target_size(original_size, image_resize)
        if target_size == original_size:
            return path.read_bytes(), inferred_mime

        resized = image.resize(target_size, Image.Resampling.LANCZOS)
        output_format, output_mime = _output_format_and_mime(image, inferred_mime)
        prepared = _prepare_for_output(resized, output_format)
        buffer = io.BytesIO()
        save_kwargs: dict[str, Any] = {"format": output_format}
        if output_format == "JPEG":
            save_kwargs.update({"quality": 95, "optimize": True})
        prepared.save(buffer, **save_kwargs)
        return buffer.getvalue(), output_mime


def _target_size(
    original_size: tuple[int, int],
    image_resize: float | int,
) -> tuple[int, int]:
    width, height = original_size
    if isinstance(image_resize, float):
        return (
            max(1, int(width * image_resize)),
            max(1, int(height * image_resize)),
        )

    longer_edge = max(width, height)
    if longer_edge <= image_resize:
        return original_size
    scale = image_resize / float(longer_edge)
    return (
        max(1, int(width * scale)),
        max(1, int(height * scale)),
    )


def _output_format_and_mime(image: Any, inferred_mime: str) -> tuple[str, str]:
    image_format = str(getattr(image, "format", "") or "").upper()
    if image_format in {"PNG", "JPEG", "WEBP"}:
        output_format = image_format
    else:
        output_format = "PNG"

    if output_format == "JPEG":
        return "JPEG", "image/jpeg"
    if output_format == "WEBP":
        return "WEBP", "image/webp"
    if inferred_mime.startswith("image/"):
        return "PNG", "image/png" if inferred_mime == "application/octet-stream" else "image/png"
    return "PNG", "image/png"


def _prepare_for_output(image: Any, output_format: str) -> Any:
    if output_format == "JPEG" and image.mode not in {"RGB", "L"}:
        return image.convert("RGB")
    return image
