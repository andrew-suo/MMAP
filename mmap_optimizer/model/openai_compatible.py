from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
from pathlib import Path
import ssl
import time
import urllib.request
from typing import Any

from mmap_optimizer.dataset.sample import SampleAsset
from mmap_optimizer.logging import get_logger, log_stage
from .client import ModelResponse

logger = get_logger(__name__)


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str | None = None, model: str | None = None, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.verify_ssl = verify_ssl

    @classmethod
    def from_env(cls, base_url: str, api_key_env: str, model: str | None = None, verify_ssl: bool = True) -> "OpenAICompatibleClient":
        return cls(base_url=base_url, api_key=os.environ.get(api_key_env), model=model, verify_ssl=verify_ssl)

    def complete(self, messages: list[dict[str, Any]], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> ModelResponse:
        payload = self._build_payload(messages=messages, model_config=model_config, response_format=response_format)
        log_stage(logger, "model_request_start", "模型请求开始",
            model=payload.get("model"), message_count=len(messages),
            temperature=payload.get("temperature"), max_tokens=payload.get("max_tokens"),
            timeout=(model_config or {}).get("timeout", 120),
            has_response_format=response_format is not None,
            has_chat_template_kwargs="chat_template_kwargs" in payload,
            enable_thinking=payload.get("chat_template_kwargs", {}).get("enable_thinking") if payload.get("chat_template_kwargs") else None,
        )
        start_time = time.perf_counter()
        try:
            body = self._post_json(payload, timeout=(model_config or {}).get("timeout", 120))
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            content = body["choices"][0]["message"]["content"]
            if content is None:
                content = ""
            usage = body.get("usage") or {}
            usage_tokens = f"{usage.get('prompt_tokens', 0)}/{usage.get('completion_tokens', 0)}"
            preview = (content or "")[:120].replace("\n", "\\n")
            log_stage(logger, "model_response_done", "模型响应完成",
                model=payload.get("model"), duration_ms=duration_ms,
                response_chars=len(content) if content else 0,
                response_preview=preview,
                usage_tokens=usage_tokens)
            return ModelResponse(raw_output=content, metadata={"usage": body.get("usage"), "response_id": body.get("id")})
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            log_stage(logger, "model_request_failed", "模型请求失败", model=payload.get("model"), duration_ms=duration_ms, error=f"{type(exc).__name__}: {exc}")
            logger.exception("[stage=model_request_failed] model=%s duration_ms=%d error=%s: %s", payload.get("model"), duration_ms, type(exc).__name__, exc)
            raise

    def complete_multimodal(self, messages: list[dict[str, Any]], assets: list[Any], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> ModelResponse:
        prepared_messages = self._messages_with_assets(messages, assets)
        payload = self._build_payload(messages=prepared_messages, model_config=model_config, response_format=response_format)
        log_stage(logger, "model_request_start", "模型请求开始",
            model=payload.get("model"), message_count=len(prepared_messages),
            asset_count=len(assets) if assets else 0,
            temperature=payload.get("temperature"), max_tokens=payload.get("max_tokens"),
            timeout=(model_config or {}).get("timeout", 120),
            has_response_format=response_format is not None,
            has_chat_template_kwargs="chat_template_kwargs" in payload,
            enable_thinking=payload.get("chat_template_kwargs", {}).get("enable_thinking") if payload.get("chat_template_kwargs") else None,
        )
        start_time = time.perf_counter()
        try:
            body = self._post_json(payload, timeout=(model_config or {}).get("timeout", 120))
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            content = body["choices"][0]["message"]["content"]
            if content is None:
                content = ""
            usage = body.get("usage") or {}
            usage_tokens = f"{usage.get('prompt_tokens', 0)}/{usage.get('completion_tokens', 0)}"
            preview = (content or "")[:120].replace("\n", "\\n")
            log_stage(logger, "model_response_done", "模型响应完成",
                model=payload.get("model"), duration_ms=duration_ms,
                response_chars=len(content) if content else 0,
                response_preview=preview,
                usage_tokens=usage_tokens)
            return ModelResponse(
                raw_output=content,
                metadata={"usage": body.get("usage"), "response_id": body.get("id"), "asset_count": len(assets)},
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            log_stage(logger, "model_request_failed", "模型请求失败", model=payload.get("model"), duration_ms=duration_ms, error=f"{type(exc).__name__}: {exc}")
            logger.exception("[stage=model_request_failed] model=%s duration_ms=%d error=%s: %s", payload.get("model"), duration_ms, type(exc).__name__, exc)
            raise

    def _build_payload(self, *, messages: list[dict[str, Any]], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> dict[str, Any]:
        cfg = model_config or {}
        chat_template_kwargs = cfg.get("chat_template_kwargs")
        if chat_template_kwargs is None:
            chat_template_kwargs = {"enable_thinking": False}
        payload: dict[str, Any] = {
            "model": cfg.get("model") or self.model,
            "messages": messages,
            "temperature": cfg.get("temperature", 0),
            "max_tokens": cfg.get("max_tokens", 2048),
            "chat_template_kwargs": chat_template_kwargs,
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
        context = None
        if not self.verify_ssl:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
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
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") in ("text", "image_url"):
                        parts.append(dict(part))
                    else:
                        parts.append({"type": "text", "text": json.dumps(part, ensure_ascii=False)})
                else:
                    parts.append({"type": "text", "text": str(part)})
            return parts
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
