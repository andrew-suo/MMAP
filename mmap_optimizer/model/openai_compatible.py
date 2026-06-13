from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
import urllib.request
from typing import Any

from mmap_optimizer.dataset.sample import SampleAsset
from .client import ModelResponse


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str | None = None, model: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    @classmethod
    def from_env(cls, base_url: str, api_key_env: str, model: str | None = None) -> "OpenAICompatibleClient":
        return cls(base_url=base_url, api_key=os.environ.get(api_key_env), model=model)

    def complete(self, messages: list[dict[str, Any]], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> ModelResponse:
        payload = self._build_payload(messages=messages, model_config=model_config, response_format=response_format)
        body = self._post_json(payload, timeout=(model_config or {}).get("timeout", 120))
        content = body["choices"][0]["message"]["content"]
        return ModelResponse(raw_output=content, metadata={"usage": body.get("usage"), "response_id": body.get("id")})

    def complete_multimodal(self, messages: list[dict[str, Any]], assets: list[Any], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> ModelResponse:
        prepared_messages = self._messages_with_assets(messages, assets)
        payload = self._build_payload(messages=prepared_messages, model_config=model_config, response_format=response_format)
        body = self._post_json(payload, timeout=(model_config or {}).get("timeout", 120))
        content = body["choices"][0]["message"]["content"]
        return ModelResponse(
            raw_output=content,
            metadata={"usage": body.get("usage"), "response_id": body.get("id"), "asset_count": len(assets)},
        )

    def _build_payload(self, *, messages: list[dict[str, Any]], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> dict[str, Any]:
        cfg = model_config or {}
        payload: dict[str, Any] = {
            "model": cfg.get("model") or self.model,
            "messages": messages,
            "temperature": cfg.get("temperature", 0),
            "max_tokens": cfg.get("max_tokens", 2048),
        }
        if response_format is not None:
            payload["response_format"] = response_format
        return payload

    def _post_json(self, payload: dict[str, Any], *, timeout: int | float = 120) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _messages_with_assets(self, messages: list[dict[str, Any]], assets: list[Any]) -> list[dict[str, Any]]:
        if not assets:
            return messages
        prepared = [dict(message) for message in messages]
        target_idx = self._last_user_message_index(prepared)
        if target_idx is None:
            prepared.append({"role": "user", "content": []})
            target_idx = len(prepared) - 1
        existing_content = prepared[target_idx].get("content", "")
        content_parts = self._content_to_parts(existing_content)
        content_parts.extend(self._asset_to_content_part(asset) for asset in assets if self._is_image_asset(asset))
        prepared[target_idx]["content"] = content_parts
        return prepared

    def _last_user_message_index(self, messages: list[dict[str, Any]]) -> int | None:
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].get("role") == "user":
                return idx
        return None

    def _content_to_parts(self, content: Any) -> list[dict[str, Any]]:
        if isinstance(content, list):
            return [dict(part) if isinstance(part, dict) else {"type": "text", "text": str(part)} for part in content]
        if isinstance(content, str):
            return [{"type": "text", "text": content}] if content else []
        return [{"type": "text", "text": json.dumps(content, ensure_ascii=False)}]

    def _asset_to_content_part(self, asset: Any) -> dict[str, Any]:
        sample_asset = self._coerce_asset(asset)
        if sample_asset.local_path:
            url = self._local_image_data_url(sample_asset.local_path, sample_asset.mime_type)
        elif sample_asset.uri:
            url = sample_asset.uri
        else:
            raise ValueError(f"Image asset {sample_asset.id!r} must provide local_path or uri")
        image_url: dict[str, Any] = {"url": url}
        detail = sample_asset.metadata.get("openai_image_detail") if sample_asset.metadata else None
        if detail:
            image_url["detail"] = detail
        return {"type": "image_url", "image_url": image_url}

    def _local_image_data_url(self, local_path: str, mime_type: str | None = None) -> str:
        path = Path(local_path)
        inferred_mime = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{inferred_mime};base64,{encoded}"

    def _is_image_asset(self, asset: Any) -> bool:
        sample_asset = self._coerce_asset(asset)
        return sample_asset.type == "image" or (sample_asset.mime_type or "").startswith("image/")

    def _coerce_asset(self, asset: Any) -> SampleAsset:
        if isinstance(asset, SampleAsset):
            return asset
        if isinstance(asset, dict):
            return SampleAsset(**asset)
        raise TypeError(f"Unsupported asset type: {type(asset)!r}")
