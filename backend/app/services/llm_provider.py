"""LLM 提供方抽象 + DeepSeek/OpenAI/Qwen 实现。

三者均兼容 OpenAI Chat Completions 协议，统一用 httpx 调用 /chat/completions (stream=true)。
"""
from __future__ import annotations

import time
from typing import AsyncGenerator, Iterator

import httpx
from sqlalchemy import select

from ..config import settings
from ..database import SessionLocal
from ..models import LLMConfig


class LLMProvider:
    """LLM 提供方抽象基类。"""

    name = "base"

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def stream_chat(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        """流式生成，逐 token yield。子类实现。"""
        raise NotImplementedError
        if False:
            yield ""

    async def chat(self, messages: list[dict]) -> str:
        """非流式：聚合 stream_chat。"""
        chunks: list[str] = []
        async for t in self.stream_chat(messages):
            chunks.append(t)
        return "".join(chunks)


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI 兼容协议实现（DeepSeek/OpenAI/Qwen 通用）。"""

    async def stream_chat(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = __import__("json").loads(data)
                        delta = obj["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        continue


# ---- 工厂 ----

_BUILTIN = {
    "deepseek": lambda c: OpenAICompatibleProvider(
        c.api_key or settings.deepseek_api_key,
        c.base_url or settings.deepseek_base_url,
        c.model or settings.deepseek_model,
    ),
    "openai": lambda c: OpenAICompatibleProvider(
        c.api_key or settings.openai_api_key,
        c.base_url or settings.openai_base_url,
        c.model or settings.openai_model,
    ),
    "qwen": lambda c: OpenAICompatibleProvider(
        c.api_key or settings.qwen_api_key,
        c.base_url or settings.qwen_base_url,
        c.model or settings.qwen_model,
    ),
}


def get_provider(provider: str | None = None, config_id: int | None = None) -> LLMProvider:
    """根据 provider 名或配置 ID 取得一个 LLMProvider 实例。"""
    db = SessionLocal()
    try:
        cfg = None
        if config_id is not None:
            cfg = db.get(LLMConfig, config_id)
        if cfg is None:
            # 取默认配置
            cfg = db.scalar(select(LLMConfig).where(LLMConfig.is_default.is_(True)))
        if cfg is None:
            # 退化到环境变量
            target = provider or settings.llm_default_provider
            key_map = {
                "deepseek": (settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model),
                "openai": (settings.openai_api_key, settings.openai_base_url, settings.openai_model),
                "qwen": (settings.qwen_api_key, settings.qwen_base_url, settings.qwen_model),
            }
            k, b, m = key_map.get(target, key_map["deepseek"])
            return OpenAICompatibleProvider(k, b, m)
        target = provider or cfg.provider
        factory = _BUILTIN.get(target, _BUILTIN["deepseek"])
        return factory(cfg)
    finally:
        db.close()


def list_available_providers() -> list[dict]:
    return [
        {"provider": "deepseek", "label": "DeepSeek", "default_model": settings.deepseek_model, "base_url": settings.deepseek_base_url},
        {"provider": "openai", "label": "OpenAI", "default_model": settings.openai_model, "base_url": settings.openai_base_url},
        {"provider": "qwen", "label": "通义千问 Qwen", "default_model": settings.qwen_model, "base_url": settings.qwen_base_url},
    ]
