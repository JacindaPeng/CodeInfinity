"""RAG 服务：检索课程知识库 → 组装 prompt → 流式生成答案。"""
from __future__ import annotations

from typing import AsyncGenerator

from . import vector_store
from .llm_provider import LLMProvider, get_provider

SYSTEM_PROMPT = """你是《C语言程序设计》课程智能体。基于下方检索到的课程资料回答学生问题。
要求：
1. 回答准确、简洁、结构清晰，必要时使用代码块或列表。
2. 只使用资料中的信息；若资料不足以回答，请明确说明并建议查阅哪些章节。
3. 回答末尾可附「相关知识点」简短提示。

【检索资料】
{context}
"""


def _build_context(hits: list[dict]) -> str:
    if not hits:
        return "（未检索到相关资料）"
    parts = []
    for i, h in enumerate(hits, 1):
        meta = h["metadata"]
        title = meta.get("title", "")
        chapter = meta.get("chapter_id", "")
        page = meta.get("page", "")
        start = meta.get("start_sec", "")
        loc = f"章节{chapter}"
        if page: loc += f" 第{page}页"
        if start: loc += f" 视频{start}s"
        parts.append(f"[{i}] 《{title}》{loc}\n{h['document']}")
    return "\n\n".join(parts)


def retrieve(question: str, chapter_id: int | None = None, k: int = 5) -> list[dict]:
    where = {"chapter_id": str(chapter_id)} if chapter_id else None
    return vector_store.query(question, n_results=k, where=where)


async def rag_stream(
    question: str,
    history: list[dict] | None = None,
    chapter_id: int | None = None,
    provider: LLMProvider | None = None,
) -> tuple[list[dict], AsyncGenerator[str, None]]:
    """返回 (检索结果, 流式生成器)。"""
    hits = retrieve(question, chapter_id=chapter_id)
    context = _build_context(hits)
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(context=context)}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": question})

    prov = provider or get_provider()
    return hits, prov.stream_chat(messages)
