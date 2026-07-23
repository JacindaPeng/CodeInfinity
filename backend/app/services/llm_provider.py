"""LLM 提供方抽象 + OpenAI 兼容协议实现。

各厂商若兼容 OpenAI Chat Completions，统一用 httpx 调用 /chat/completions (stream=true)。
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

import httpx
from sqlalchemy import select

from ..config import Settings, settings
from ..database import SessionLocal
from ..models import LLMConfig

# 代理/长回答场景：读超时放宽；连接掐断时自动重试
_LLM_TIMEOUT = httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=20.0)
_RETRYABLE = (
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.ProxyError,
)


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
    """OpenAI 兼容协议实现（DeepSeek/OpenAI/Qwen 等通用）。"""

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, messages: list[dict], *, stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": 0.7,
        }

    async def _stream_once(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/chat/completions"
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
            async with client.stream(
                "POST", url, json=self._payload(messages, stream=True), headers=self._headers(),
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="ignore")[:300]
                    raise httpx.HTTPStatusError(
                        f"LLM HTTP {resp.status_code}: {body}",
                        request=resp.request,
                        response=resp,
                    )
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        continue

    async def _chat_once(self, messages: list[dict]) -> str:
        """非流式兜底，避免流被代理中途掐断后整问失败。"""
        url = f"{self.base_url}/chat/completions"
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
            resp = await client.post(
                url, json=self._payload(messages, stream=False), headers=self._headers(),
            )
            resp.raise_for_status()
            obj = resp.json()
            return (((obj.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""

    async def stream_chat(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        last_err: Exception | None = None
        for attempt in range(3):
            got_any = False
            try:
                async for token in self._stream_once(messages):
                    got_any = True
                    yield token
                return
            except _RETRYABLE as e:
                last_err = e
                # 已输出部分内容则结束，避免重复段落
                if got_any:
                    return
                await asyncio.sleep(0.5 * (attempt + 1))
            except httpx.HTTPStatusError as e:
                last_err = e
                break

        # 流式三次仍失败：改一次非流式
        try:
            text = await self._chat_once(messages)
            if text:
                yield text
                return
        except Exception as e:
            last_err = e

        hint = str(last_err) if last_err else "未知错误"
        if "incomplete chunked" in hint or "peer closed" in hint.lower():
            hint = "上游连接中断（代理或不稳定网络），已重试仍失败，请稍后再试或换一个模型"
        raise RuntimeError(f"LLM 调用失败: {hint}") from last_err


# ---- 提供商注册表 ----

_PROVIDER_SPECS: list[tuple[str, str, str, str, str]] = [
    # (id, 显示名, api_key 字段, base_url 字段, model 字段)
    ("deepseek", "DeepSeek", "deepseek_api_key", "deepseek_base_url", "deepseek_model"),
    ("qwen", "通义千问 Qwen", "qwen_api_key", "qwen_base_url", "qwen_model"),
    ("openai", "OpenAI (Jeniya)", "openai_api_key", "openai_base_url", "openai_model"),
    ("gemini", "Google Gemini (Jeniya)", "gemini_api_key", "gemini_base_url", "gemini_model"),
    ("claude", "Claude (Jeniya)", "claude_api_key", "claude_base_url", "claude_model"),
    ("moonshot", "月之暗面 Kimi", "moonshot_api_key", "moonshot_base_url", "moonshot_model"),
    ("zhipu", "智谱 GLM", "zhipu_api_key", "zhipu_base_url", "zhipu_model"),
]


def _provider_defaults(provider_id: str, cfg: Settings | LLMConfig | None = None) -> tuple[str, str, str]:
    for pid, _, key_attr, url_attr, model_attr in _PROVIDER_SPECS:
        if pid == provider_id:
            if cfg is None:
                cfg = settings
            api_key = getattr(cfg, key_attr, "") if hasattr(cfg, key_attr) else ""
            base_url = getattr(cfg, url_attr, "")
            model = getattr(cfg, model_attr, "")
            return api_key, base_url, model
    return "", "", ""


def _make_provider(provider_id: str, cfg: LLMConfig | Settings) -> LLMProvider:
    env_key, env_url, env_model = _provider_defaults(provider_id, settings)
    api_key = getattr(cfg, "api_key", None) or env_key
    base_url = getattr(cfg, "base_url", None) or env_url
    model = getattr(cfg, "model", None) or env_model
    if not api_key or not base_url or not model:
        # 未知 provider 或未配置时回退 deepseek 环境变量
        api_key = api_key or settings.deepseek_api_key
        base_url = base_url or settings.deepseek_base_url
        model = model or settings.deepseek_model
    return OpenAICompatibleProvider(api_key, base_url, model)


def get_provider(provider: str | None = None, config_id: int | None = None) -> LLMProvider:
    """根据 provider 名或配置 ID 取得一个 LLMProvider 实例。"""
    db = SessionLocal()
    try:
        cfg = None
        if config_id is not None:
            cfg = db.get(LLMConfig, config_id)
        if cfg is None:
            cfg = db.scalar(select(LLMConfig).where(LLMConfig.is_default.is_(True)))
        if cfg is None:
            target = provider or settings.llm_default_provider
            return _make_provider(target, settings)
        target = provider or cfg.provider
        return _make_provider(target, cfg)
    finally:
        db.close()


def list_available_providers() -> list[dict]:
    return [
        {
            "provider": pid,
            "label": label,
            "default_model": getattr(settings, model_attr),
            "base_url": getattr(settings, url_attr),
        }
        for pid, label, _key, url_attr, model_attr in _PROVIDER_SPECS
    ]
