"""RAG 服务：检索课程知识库 → 组装 prompt → 流式生成答案。

检索策略：关键词搜索（主）+ 向量搜索（辅）混合检索。
关键词搜索不依赖嵌入模型的语言能力，对中文内容更精准。
"""
from __future__ import annotations

import re
from typing import AsyncGenerator

from . import vector_store
from .llm_provider import LLMProvider, get_provider

SYSTEM_PROMPT = """你是《C程序设计快速进阶大学教程》课程智能体。基于下方检索到的课程资料回答学生问题。
要求：
1. 回答准确、简洁、结构清晰，必要时使用代码块或列表。
2. 优先使用资料中的信息；若资料不足以完整回答，可结合 C 语言通用知识补充，但要说明来源。
3. 若检索资料为空或与问题无关，请基于 C 语言专业知识回答，并建议查阅教材对应章节。
4. 回答末尾请附「参考资料」列出引用的资料来源（章节名+页码），方便学生定位原文。
5. 如果检索资料中包含具体页码信息，务必在回答中引用（如"详见第5章 数据类型与输入输出 PDF第72页"），页码指PDF页码。

【检索资料】
{context}
"""

ATTACHMENT_SYSTEM_PROMPT = """你是《C程序设计快速进阶大学教程》课程智能体。学生上传了附件（试卷/测验/练习题等），并提问如何从附件中归纳考点、推荐复习资源。

**回答原则（必须遵守）：**
1. **必须先完整阅读用户消息中的附件内容**，从中归纳本次测试/练习真正涉及的考点、知识点与题型。
2. **禁止**脱离附件泛泛罗列教材「重点章节」、MOOC 视频或资料库外的资源；附件未出现的内容不要列为本次考点。
3. **「推荐学习资源」必须且只能引用下方「可推荐的课程资料」列表**中的条目，写明资料标题、类型（pdf/ppt/video）及 **PDF 页码** 或 **视频秒数**，并说明与哪个考点对应。
4. 若某考点在「可推荐的课程资料」中无匹配项，如实写「资料库暂无匹配，建议补充上传」；不要编造页码或章节名。
5. 建议结构：先列「附件涉及的考点」，再列「推荐学习资源（来自资料管理）」表格，说明考点与资料的对应关系。
6. 下方「检索资料片段」仅供理解上下文，推荐时以「可推荐的课程资料」列表为准。

【可推荐的课程资料】（来自教师在「资料管理」中上传并已索引的资源，推荐时必须引用）
{recommendations}

【检索资料片段】（辅助理解，推荐资源以列表为准）
{context}
"""


def _build_context(hits: list[dict]) -> str:
    if not hits:
        return "（未检索到直接相关资料，请基于 C 语言专业知识回答）"
    parts = []
    for i, h in enumerate(hits, 1):
        meta = h["metadata"]
        title = meta.get("title", "")
        chapter_title = meta.get("chapter_title", "")
        page = meta.get("page", "")
        start = meta.get("start_sec", "")
        loc = chapter_title if chapter_title else f"章节{meta.get('chapter_id', '')}"
        if page: loc += f" PDF第{page}页"
        if start: loc += f" 视频{start}s"
        parts.append(f"[{i}] 《{title}》{loc}\n{h['document']}")
    return "\n\n".join(parts)


# 常见问题词/停用词，提取关键词时排除
_STOP_WORDS = set(
    "什么 是 的 怎么 如何 为什么 哪 一个 哪些 那些 这个 那个 在 和 与 及 或 请 告诉 我 你 他 她 它 "
    "关于 对于 通过 使用 用 被 把 给 对 从 到 中 里 上面 下面 前面 后面 哪个 什么意思 意思 解释 一下 说 讲 介绍 "
    "根据 这次 测试 内容 考点 推荐 相关 学习 资源 告诉 上传 附件 用户 以下 文件 题目 试卷 测验 练习".split()
)


def _extract_keywords(question: str) -> list[str]:
    """从中文问题中提取关键词（2字以上的中文词组）。"""
    text = question
    # 先把停用词替换为空格（用边界匹配避免误删）
    for sw in sorted(_STOP_WORDS, key=len, reverse=True):
        text = text.replace(sw, " ")
    # 移除标点
    text = re.sub(r"[？?！!。，,\.；;：:、\s]+", " ", text)
    # 提取中文词组（2个以上连续中文字符）
    segments = re.findall(r"[\u4e00-\u9fa5]{2,}", text)
    # 提取英文单词
    segments += re.findall(r"[a-zA-Z_]{2,}", text)
    # 过滤停用词（再过滤一次，防止替换后产生的片段是停用词）
    keywords = [s for s in segments if s not in _STOP_WORDS and len(s) >= 2]
    return keywords if keywords else [question.strip()]


def _build_where(chapter_id: int | None, class_ids: list[int] | None) -> dict | None:
    """构建 Chroma where 过滤条件。"""
    clauses: list[dict] = []
    if chapter_id is not None:
        clauses.append({"chapter_id": str(chapter_id)})
    if class_ids is not None:
        if not class_ids:
            return {"class_id": "__none__"}
        if len(class_ids) == 1:
            clauses.append({"class_id": str(class_ids[0])})
        else:
            clauses.append({"class_id": {"$in": [str(c) for c in class_ids]}})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _keyword_search(
    keywords: list[str],
    chapter_id: int | None = None,
    class_ids: list[int] | None = None,
    limit: int = 10,
) -> list[dict]:
    """用 Chroma 的 where_document $contains 做关键词搜索。过滤目录页。"""
    col = vector_store.get_collection()
    results: list[dict] = []
    seen_ids: set[str] = set()

    where = _build_where(chapter_id, class_ids)

    def _is_toc(text: str) -> bool:
        """检测是否为目录页（含大量点引导符）。"""
        dot_count = text[:300].count("…") + text[:300].count("．．") + text[:300].count("...")
        return dot_count > 5

    for kw in keywords:
        try:
            # 不限 limit，获取所有匹配的 chunk（确保跨章节覆盖）
            res = col.get(
                where_document={"$contains": kw},
                where=where,
                limit=10000,
            )
            docs = res.get("documents", [])
            metas = res.get("metadatas", [])
            ids = res.get("ids", [])
            for doc, meta, id_ in zip(docs, metas, ids):
                if id_ not in seen_ids and not _is_toc(doc):
                    seen_ids.add(id_)
                    results.append({
                        "document": doc,
                        "metadata": meta,
                        "distance": 0.0,
                        "keyword": kw,
                    })
        except Exception:
            continue

    # 如果限定章节无结果，尝试放宽章节限制（仍保持班级隔离）
    if not results and chapter_id:
        for kw in keywords:
            try:
                res = col.get(
                    where_document={"$contains": kw},
                    where=_build_where(None, class_ids),
                    limit=10000,
                )
                docs = res.get("documents", [])
                metas = res.get("metadatas", [])
                ids = res.get("ids", [])
                for doc, meta, id_ in zip(docs, metas, ids):
                    if id_ not in seen_ids and not _is_toc(doc):
                        seen_ids.add(id_)
                        results.append({
                            "document": doc,
                            "metadata": meta,
                            "distance": 0.0,
                            "keyword": kw,
                        })
            except Exception:
                continue

    return results


def retrieve(
    question: str,
    chapter_id: int | None = None,
    class_ids: list[int] | None = None,
    k: int | None = None,
) -> list[dict]:
    """混合检索：关键词搜索（主）+ 向量搜索（辅）。"""
    if class_ids is not None and not class_ids:
        return []
    if k is None:
        k = max(5, len(question) // 20)

    # 1. 关键词搜索（多取一些确保覆盖所有相关章节）
    keywords = _extract_keywords(question)
    keyword_hits = _keyword_search(keywords, chapter_id=chapter_id, class_ids=class_ids, limit=30)

    # 2. 向量搜索（作为补充）
    where = _build_where(chapter_id, class_ids)
    vector_hits = vector_store.query(question, n_results=k, where=where)
    if not vector_hits and chapter_id:
        vector_hits = vector_store.query(question, n_results=k, where=_build_where(None, class_ids))

    # 3. 合并去重
    seen_docs: set[str] = set()
    merged: list[dict] = []

    for h in keyword_hits:
        doc_key = h["document"][:100]
        if doc_key not in seen_docs:
            seen_docs.add(doc_key)
            merged.append(h)

    for h in vector_hits:
        doc_key = h["document"][:100]
        if doc_key not in seen_docs:
            seen_docs.add(doc_key)
            merged.append(h)

    # 4. 排序优化：章节标题包含关键词的 chunk 优先
    def _rank_key(h: dict) -> tuple:
        meta = h.get("metadata", {})
        chapter_title = meta.get("chapter_title", "")
        keyword = h.get("keyword", "")
        # 章节标题包含搜索关键词 → 排在前面
        title_boost = 0 if (keyword and keyword in chapter_title) else 1
        distance = h.get("distance", 1.0)
        return (title_boost, distance)

    merged.sort(key=_rank_key)
    return merged[:k * 2]


async def rag_stream(
    question: str,
    history: list[dict] | None = None,
    chapter_id: int | None = None,
    class_ids: list[int] | None = None,
    provider: LLMProvider | None = None,
    search_query: str | None = None,
    has_attachments: bool = False,
    recommendations_text: str = "",
    precomputed_hits: list[dict] | None = None,
) -> tuple[list[dict], AsyncGenerator[str, None]]:
    """返回 (检索结果, 流式生成器)。"""
    query_for_retrieve = (search_query or question).strip()
    hits = precomputed_hits if precomputed_hits is not None else retrieve(
        query_for_retrieve, chapter_id=chapter_id, class_ids=class_ids,
    )
    context = _build_context(hits)
    if has_attachments:
        prompt_tpl = ATTACHMENT_SYSTEM_PROMPT
        system_content = prompt_tpl.format(
            context=context,
            recommendations=recommendations_text or "（暂无匹配资料）",
        )
    else:
        system_content = SYSTEM_PROMPT.format(context=context)
    messages = [{"role": "system", "content": system_content}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": question})

    prov = provider or get_provider()
    return hits, prov.stream_chat(messages)
