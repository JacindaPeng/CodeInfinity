"""RAG 服务：检索课程知识库 → 组装 prompt → 流式生成答案。

检索策略：关键词搜索（主）+ 向量搜索（辅）混合检索。
关键词搜索不依赖嵌入模型的语言能力，对中文内容更精准。
"""
from __future__ import annotations

import asyncio
import re
from typing import AsyncGenerator

from . import vector_store
from .llm_provider import LLMProvider, get_provider

SYSTEM_PROMPT = """你是《C程序设计快速进阶大学教程》课程智能体。基于下方检索到的课程资料回答学生问题。
要求：
1. 回答准确、简洁、结构清晰，必要时使用代码块或列表。
2. 优先使用资料中的信息；若资料不足以完整回答，可结合 C 语言通用知识补充，但要说明来源。
3. 若检索资料为空或与问题无关，请基于 C 语言专业知识回答，并建议查阅教材对应章节。
4. 回答末尾请附「参考资料」列出引用的资料来源（章节名+页码/视频时间），方便学生定位。
5. 如果检索资料中包含具体页码信息，务必在回答中引用（如"详见第5章 数据类型与输入输出 PDF第72页"），页码指PDF页码。
6. **下方「可推荐学习资源」来自教师已上传并索引的资料（含 PDF/PPT/视频）。若列表中有 type=video 的条目，必须在回答中明确推荐该视频（写标题与时间点），严禁声称「没有视频」「未找到视频资源」。**
7. 「可推荐学习资源」列表以外的链接/课程名不要编造。
8. **若「可推荐学习资源」为空或写明暂无匹配，不要输出「建议学习」清单，也不要假装推荐了资料库条目；可基于通识回答，并说明资料库未检索到直接对应条目。**

【可推荐学习资源】（来自资料管理；为空则勿编造推荐）
{recommendations}

【检索资料】
{context}
"""

JAVA_SYSTEM_PROMPT = """你是 Java 程序设计课程智能体。基于下方检索到的课程资料回答学生问题。
要求：
1. 回答准确、简洁，必要时使用 Java 代码示例。
2. 优先使用资料中的信息；不足时可结合 Java 通用知识补充并说明。
3. 若检索资料为空，请基于 Java 专业知识回答，并建议查阅教材对应章节。
4. 回答末尾附「参考资料」列出引用的资料来源（章节名+页码/视频时间）。
5. **若「可推荐学习资源」中有视频，必须推荐并写明标题与时间点，禁止声称没有视频。**
6. 若「可推荐学习资源」为空，不要编造建议学习清单。

【可推荐学习资源】
{recommendations}

【检索资料】
{context}
"""

PYTHON_SYSTEM_PROMPT = """你是 Python 程序设计课程智能体。基于下方检索到的课程资料回答学生问题。
要求：
1. 回答准确、简洁，必要时使用 Python 代码示例。
2. **必须优先使用检索资料中的内容**；若资料中有与问题相关的段落，必须据此回答，**禁止**声称「资料未涉及」「资料未直接涉及」。
3. 若检索资料足以回答，不得脱离资料泛泛发挥；不足时可结合 Python 通用知识补充并说明。
4. 回答末尾附「参考资料」列出引用的资料来源（章节名 + **PDF 页码**/视频时间），页码必须与检索片段 metadata 一致。
5. 「推荐学习资源」或参考资料中的页码、章节名必须来自检索资料或下方列表，不得编造。
6. **若「可推荐学习资源」中有视频，必须推荐并写明标题与时间点，禁止声称没有视频。**
7. 若「可推荐学习资源」为空，不要编造建议学习清单。

【可推荐学习资源】
{recommendations}

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

JAVA_ATTACHMENT_SYSTEM_PROMPT = """你是 Java 程序设计课程智能体。学生上传了附件（试卷/测验/练习题等），并提问如何从附件中归纳考点、推荐复习资源。

**回答原则（必须遵守）：**
1. **必须先完整阅读用户消息中的附件内容**，从中归纳本次测试/练习真正涉及的考点、知识点与题型。
2. **禁止**脱离附件泛泛罗列教材章节；附件未出现的内容不要列为本次考点。
3. **「推荐学习资源」必须且只能引用下方「可推荐的课程资料」列表**中的条目，写明资料标题、类型及 **PDF 页码** 或 **视频秒数**。
4. 若某考点在列表中无匹配项，如实写「资料库暂无匹配，建议补充上传」。
5. 建议结构：先列「附件涉及的考点」，再列「推荐学习资源（来自资料管理）」。

【可推荐的课程资料】
{recommendations}

【检索资料片段】
{context}
"""

PYTHON_ATTACHMENT_SYSTEM_PROMPT = """你是 Python 程序设计课程智能体。学生上传了附件（试卷/测验/练习题等），并提问如何从附件中归纳考点、推荐复习资源。

**回答原则（必须遵守）：**
1. **必须先完整阅读用户消息中的附件内容**，从中归纳本次测试/练习真正涉及的考点、知识点与题型。
2. **禁止**脱离附件泛泛罗列教材章节；附件未出现的内容不要列为本次考点。
3. **「推荐学习资源」必须且只能引用下方「可推荐的课程资料」列表**中的条目，写明资料标题、类型及 **PDF 页码** 或 **视频秒数**。
4. 若某考点在列表中无匹配项，如实写「资料库暂无匹配，建议补充上传」。
5. 建议结构：先列「附件涉及的考点」，再列「推荐学习资源（来自资料管理）」。

【可推荐的课程资料】
{recommendations}

【检索资料片段】
{context}
"""

_PROMPTS_BY_SLUG: dict[str, tuple[str, str]] = {
    "c-lang": (SYSTEM_PROMPT, ATTACHMENT_SYSTEM_PROMPT),
    "java": (JAVA_SYSTEM_PROMPT, JAVA_ATTACHMENT_SYSTEM_PROMPT),
    "python": (PYTHON_SYSTEM_PROMPT, PYTHON_ATTACHMENT_SYSTEM_PROMPT),
}

_DEFAULT_LANG_HINT = {
    "c-lang": "C 语言",
    "java": "Java",
    "python": "Python",
}


def get_prompt_templates(agent_slug: str | None) -> tuple[str, str]:
    """按智能体 slug 返回 (普通问答, 附件问答) 系统提示词模板。"""
    if agent_slug and agent_slug in _PROMPTS_BY_SLUG:
        return _PROMPTS_BY_SLUG[agent_slug]
    return SYSTEM_PROMPT, ATTACHMENT_SYSTEM_PROMPT


def _fallback_lang_hint(agent_slug: str | None) -> str:
    return _DEFAULT_LANG_HINT.get(agent_slug or "", "课程")


def _build_context(hits: list[dict], agent_slug: str | None = None) -> str:
    if not hits:
        lang = _fallback_lang_hint(agent_slug)
        return f"（未检索到直接相关资料，请基于 {lang} 专业知识回答）"
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


# 常见问题词/停用词，提取关键词时排除（勿用单字，否则会拆掉「里奇」「中国」等人名/专名）
_STOP_WORDS = set(
    "什么 怎么 如何 为什么 哪个 哪些 那些 这个 那个 关于 对于 通过 使用 "
    "上面 下面 前面 后面 什么意思 意思 解释 一下 介绍 告诉 "
    "根据 这次 测试 内容 考点 推荐 相关 学习 资源 上传 附件 用户 以下 文件 题目 试卷 测验 练习 "
    "谁是 是谁 请问 一下".split()
)

# 课程专名：无空格长句里用来二次切出考点（如「详细讲讲数组」→「数组」）
_DOMAIN_TERMS = frozenset({
    "数组", "指针", "函数", "递归", "字符串", "字符数组", "二维数组", "行指针",
    "结构体", "共用体", "枚举", "宏定义", "预处理", "文件", "链表", "栈", "队列",
    "排序", "冒泡", "选择排序", "快速排序", "二分", "循环", "分支", "条件",
    "丹尼斯", "里奇", "汤普逊", "汤普森", "操作系统", "编译器",
    "numpy", "pandas", "dataframe", "ndarray",
})


def _extract_keywords(question: str) -> list[str]:
    """从中文问题中提取关键词（2字以上的中文词组）。"""
    # 统一间隔符，避免「丹尼斯·里奇」无法切词
    raw = question or ""
    text = re.sub(r"[·•・．.‧･]", " ", raw)
    for sw in sorted(_STOP_WORDS, key=len, reverse=True):
        if len(sw) < 2:
            continue
        text = text.replace(sw, " ")
    text = re.sub(r"[？?！!。，,\.；;：:、\s]+", " ", text)
    segments = re.findall(r"[\u4e00-\u9fa5]{2,}", text)
    segments += re.findall(r"[a-zA-Z_]{2,}", text)
    keywords = [s for s in segments if s not in _STOP_WORDS and len(s) >= 2]

    # 长中文块（「详细讲讲数组」）再拆出领域专名
    for term in sorted(_DOMAIN_TERMS, key=len, reverse=True):
        if term in raw and term not in keywords and term not in _STOP_WORDS:
            keywords.append(term)

    # 丢掉过长叙述块（已抽出专名后）
    keywords = [
        k for k in keywords
        if len(k) <= 8 or any(t in k for t in _DOMAIN_TERMS)
    ]
    return keywords if keywords else ([raw.strip()] if raw.strip() else [])


# 过于宽泛、易误命中大量无关页的关键词
_GENERIC_KEYWORDS = frozenset({
    "字符串", "函数", "变量", "数据", "类型", "方法", "对象", "模块", "程序", "代码",
    "语法", "定义", "使用", "操作", "基础", "简介", "相互", "相互转换", "转换", "介绍",
    "说明", "概念", "理解", "学习", "内容", "问题", "相关", "详细", "讲讲",
})

_TOPIC_EXPANSIONS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("datetime", "时间", "日期", "timestamp", "时间序列"), ("datetime", "strftime", "strptime", "to_datetime", "Timestamp")),
    (("字符串", "datetime"), ("strftime", "strptime", "to_datetime", "格式化")),
    (("pandas", "pd"), ("to_datetime", "Timestamp", "DatetimeIndex")),
    (("数组", "numpy", "ndarray"), ("numpy", "array", "ndarray", "dtype", "下标", "元素")),
    (("二维数组", "矩阵"), ("二维数组", "行", "列", "下标")),
    (("指针", "地址"), ("指针", "取地址", "解引用", "&", "*")),
    (("循环", "for", "while"), ("循环", "for", "while", "do while", "迭代")),
    (("递归",), ("递归", "递归调用", "递归出口")),
    (("结构体", "struct"), ("结构体", "struct", "成员")),
    (("dataframe", "数据框"), ("DataFrame", "read_csv", "columns")),
    # 人名/史实：OCR 常把 Dennis Ritchie 扫成 RITCH / DenMn.i Rsitice
    (
        ("丹尼斯", "里奇", "ritchie", "dennis", "肯汤普", "汤普逊", "汤普森"),
        ("RITCH", "RITCHIE", "Dennis", "DenMn", "UNIX", "B语言", "BCPL", "贝尔实验室", "C语言发展史"),
    ),
]


def _expand_query_keywords(question: str, keywords: list[str]) -> list[str]:
    """根据问题语义扩展检索词，避免仅命中泛词而漏掉精确页码。"""
    q = question.strip()
    q_lower = q.lower()
    out: list[str] = []
    seen: set[str] = set()

    def _add(term: str, front: bool = False) -> None:
        key = term.lower()
        if not term or key in seen:
            return
        seen.add(key)
        if front:
            out.insert(0, term)
        else:
            out.append(term)

    for kw in keywords:
        _add(kw)
    for triggers, extras in _TOPIC_EXPANSIONS:
        if any(t in q_lower or t in q for t in triggers):
            for term in extras:
                _add(term, front=True)
    return out or keywords


def _keyword_specificity(kw: str) -> int:
    if kw in _GENERIC_KEYWORDS:
        return 0
    if re.match(r"[a-zA-Z_][a-zA-Z0-9_.]{2,}", kw):
        return 3
    if len(kw) >= 4:
        return 2
    return 1


def _doc_matches_kw(doc: str, kw: str) -> bool:
    if not doc or not kw:
        return False
    if kw in doc:
        return True
    return kw.lower() in doc.lower()


def _score_retrieval_hit(h: dict, keywords: list[str]) -> tuple:
    doc = h.get("document") or ""
    specific = 0
    matched = 0
    for kw in keywords:
        if _doc_matches_kw(doc, kw):
            matched += 1
            specific += _keyword_specificity(kw)
    meta = h.get("metadata", {})
    chapter_title = meta.get("chapter_title", "")
    keyword = h.get("keyword", "")
    title_boost = 1 if (keyword and keyword in chapter_title) else 0
    distance = float(h.get("distance", 1.0))
    return (specific, matched, title_boost, -distance)


def _build_where(
    chapter_id: int | None,
    class_ids: list[int] | None,
    course_id: int | None = None,
    agent_id: int | None = None,
) -> dict | None:
    """构建 Chroma where：只使用 class_id / chapter_id。

    Docker 下在 where 里加 course_id、agent_id 或 where_document.$contains
    会导致数十秒级全表扫描；course_id / agent_id 改在 Python 侧过滤。
    """
    _ = (course_id, agent_id)  # 由 _meta_matches_scope 处理
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


def _meta_matches_scope(
    meta: dict | None,
    *,
    chapter_id: int | None = None,
    class_ids: list[int] | None = None,
    course_id: int | None = None,
    agent_id: int | None = None,
    enforce_chapter: bool = True,
) -> bool:
    """在内存中校验 chunk 是否属于当前检索范围。"""
    meta = meta or {}
    if enforce_chapter and chapter_id is not None:
        if str(meta.get("chapter_id") or "") != str(chapter_id):
            return False
    if class_ids is not None:
        try:
            cid = int(meta.get("class_id"))
        except (TypeError, ValueError):
            return False
        if cid not in class_ids:
            return False
    if course_id is not None:
        mc = str(meta.get("course_id") or "")
        # 旧索引常缺 course_id：缺省放行；有值则必须匹配
        if mc and mc != str(course_id):
            return False
    if agent_id is not None:
        if str(meta.get("agent_id") or "") != str(agent_id):
            return False
    return True


def _usable_keywords(keywords: list[str], max_n: int = 8) -> list[str]:
    """去掉运算符/过短噪声词，并按专指度截断，避免无效扫描。"""
    out: list[str] = []
    seen: set[str] = set()
    for kw in sorted(keywords, key=_keyword_specificity, reverse=True):
        if not kw or kw in seen:
            continue
        if re.fullmatch(r"[\W_]+", kw):
            continue
        if len(kw) < 2:
            continue
        seen.add(kw)
        out.append(kw)
        if len(out) >= max_n:
            break
    return out


def _is_toc_chunk(text: str) -> bool:
    """检测是否为目录页（含大量点引导符）。"""
    head = (text or "")[:300]
    return head.count("…") + head.count("．．") + head.count("...") > 5


def _fetch_scope_docs(
    chapter_id: int | None,
    class_ids: list[int] | None,
    course_id: int | None = None,
    agent_id: int | None = None,
) -> list[tuple[str, dict, str]]:
    """按班级/章节一次取出候选 chunk（不做 $contains）。"""
    col = vector_store.get_collection()
    where = _build_where(chapter_id, class_ids)
    try:
        res = col.get(where=where, limit=10000, include=["documents", "metadatas"])
    except Exception:
        return []
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    ids = res.get("ids") or []
    out: list[tuple[str, dict, str]] = []
    for doc, meta, id_ in zip(docs, metas, ids):
        if not doc or _is_toc_chunk(doc):
            continue
        if not _meta_matches_scope(
            meta,
            chapter_id=chapter_id,
            class_ids=class_ids,
            course_id=course_id,
            agent_id=agent_id,
            enforce_chapter=chapter_id is not None,
        ):
            continue
        out.append((doc, meta or {}, id_))
    return out


def _keyword_search(
    keywords: list[str],
    chapter_id: int | None = None,
    class_ids: list[int] | None = None,
    course_id: int | None = None,
    agent_id: int | None = None,
    limit: int = 10,
) -> list[dict]:
    """关键词搜索：Chroma 按班级取候选，再在内存中匹配关键词。"""
    keywords = _usable_keywords(keywords)
    if not keywords:
        return []

    def _match(docs: list[tuple[str, dict, str]]) -> list[dict]:
        results: list[dict] = []
        seen_ids: set[str] = set()
        per_kw_added: dict[str, int] = {kw: 0 for kw in keywords}
        for doc, meta, id_ in docs:
            if id_ in seen_ids:
                continue
            hit_kw = ""
            for kw in keywords:
                cap = 8 if kw in _GENERIC_KEYWORDS else 40
                if per_kw_added[kw] >= cap:
                    continue
                if _doc_matches_kw(doc, kw):
                    hit_kw = kw
                    per_kw_added[kw] += 1
                    break
            if not hit_kw:
                continue
            seen_ids.add(id_)
            results.append({
                "document": doc,
                "metadata": meta,
                "distance": 0.0,
                "keyword": hit_kw,
            })
            if len(results) >= max(limit, 30):
                break
        return results

    docs = _fetch_scope_docs(chapter_id, class_ids, course_id=course_id, agent_id=agent_id)
    results = _match(docs)
    # 限定章节无结果时放宽章节（仍保持班级/课程隔离）
    if not results and chapter_id is not None:
        docs = _fetch_scope_docs(None, class_ids, course_id=course_id, agent_id=agent_id)
        results = _match(docs)
    return results


def retrieve(
    question: str,
    chapter_id: int | None = None,
    class_ids: list[int] | None = None,
    course_id: int | None = None,
    k: int | None = None,
    agent_id: int | None = None,
) -> list[dict]:
    """混合检索：关键词搜索（主）+ 向量搜索（辅）。"""
    if class_ids is not None and not class_ids and agent_id is None:
        return []
    if k is None:
        k = max(5, len(question) // 20)

    # 1. 关键词搜索：扩展语义词，优先检索专业术语
    raw_keywords = _extract_keywords(question)
    keywords = _usable_keywords(_expand_query_keywords(question, raw_keywords))
    keyword_hits = _keyword_search(
        keywords, chapter_id=chapter_id, class_ids=class_ids, course_id=course_id,
        agent_id=agent_id, limit=30,
    )

    # 2. 向量搜索（作为补充）；where 仅用 class/chapter，再内存过滤 course/agent
    where = _build_where(chapter_id, class_ids)
    vector_hits = [
        h for h in vector_store.query(question, n_results=max(k * 3, 12), where=where)
        if _meta_matches_scope(
            h.get("metadata"),
            chapter_id=chapter_id,
            class_ids=class_ids,
            course_id=course_id,
            agent_id=agent_id,
            enforce_chapter=chapter_id is not None,
        )
    ]
    if not vector_hits and chapter_id:
        vector_hits = [
            h for h in vector_store.query(
                question, n_results=max(k * 3, 12), where=_build_where(None, class_ids),
            )
            if _meta_matches_scope(
                h.get("metadata"),
                chapter_id=None,
                class_ids=class_ids,
                course_id=course_id,
                agent_id=agent_id,
                enforce_chapter=False,
            )
        ]

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

    # 兼容旧索引：仍为空时去掉 course_id 再检索一次
    if not merged and course_id is not None:
        return retrieve(
            question, chapter_id=chapter_id, class_ids=class_ids, course_id=None, k=k,
            agent_id=agent_id,
        )

    # 4. 按多关键词匹配度排序，避免泛词（如「字符串」）挤占精确页码
    merged.sort(key=lambda h: _score_retrieval_hit(h, keywords), reverse=True)
    return merged[: max(k * 2, 10)]


async def retrieve_async(
    question: str,
    chapter_id: int | None = None,
    class_ids: list[int] | None = None,
    course_id: int | None = None,
    k: int | None = None,
    agent_id: int | None = None,
) -> list[dict]:
    """在线程池执行同步检索，避免阻塞 uvicorn 事件循环（切页等其它 API 可继续响应）。"""
    return await asyncio.to_thread(
        retrieve,
        question,
        chapter_id,
        class_ids,
        course_id,
        k,
        agent_id,
    )


async def rag_stream(
    question: str,
    history: list[dict] | None = None,
    chapter_id: int | None = None,
    class_ids: list[int] | None = None,
    course_id: int | None = None,
    agent_slug: str | None = None,
    provider: LLMProvider | None = None,
    search_query: str | None = None,
    has_attachments: bool = False,
    recommendations_text: str = "",
    precomputed_hits: list[dict] | None = None,
) -> tuple[list[dict], AsyncGenerator[str, None]]:
    """返回 (检索结果, 流式生成器)。"""
    query_for_retrieve = (search_query or question).strip()
    if precomputed_hits is not None:
        hits = precomputed_hits
    else:
        hits = await retrieve_async(
            query_for_retrieve, chapter_id=chapter_id, class_ids=class_ids, course_id=course_id,
        )
    context = _build_context(hits, agent_slug)
    normal_tpl, attach_tpl = get_prompt_templates(agent_slug)
    rec_block = recommendations_text or "（暂无匹配的已上传资源）"
    if has_attachments:
        system_content = attach_tpl.format(
            context=context,
            recommendations=rec_block,
        )
    else:
        system_content = normal_tpl.format(
            context=context,
            recommendations=rec_block,
        )
    messages = [{"role": "system", "content": system_content}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": question})

    prov = provider or get_provider()
    return hits, prov.stream_chat(messages)
