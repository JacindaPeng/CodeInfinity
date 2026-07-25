"""资源推荐服务：基于检索命中的 chunk 反查 materials + chapters，
对视频 chunk 返回精准时间戳，实现「定位视频时间对应知识点」。
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Chapter, Material


# C 语言常见考点词，用于从试卷附件中提取检索关键词
_C_TOPIC_TERMS = (
    "指针", "数组", "函数", "递归", "字符串", "字符数组", "二维数组", "行指针",
    "strcmp", "strlen", "strcpy", "extern", "static", "宏定义", "define",
    "sizeof", "作用域", "存储类别", "全局变量", "局部变量", "形参", "实参",
    "回文", "子串", "进制", "二进制", "gets", "scanf", "printf",
    "自增", "自减", "屏蔽", "传值", "传址", "地址", "偏移",
    "循环", "分支", "结构体", "联合体", "枚举", "文件", "预处理",
)

# 课件 ASR 常见错辨 → 写入检索时一并匹配字幕
_ASR_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "数组": ("数组", "数族", "数租"),
    "二维数组": ("二维数组", "2维数组", "两维数组"),
    "指针": ("指针", "指正", "只针"),
    "循环": ("循环", "寻环", "循还"),
    "递归": ("递归", "地归", "递龟"),
    "结构体": ("结构体", "结购体"),
    "字符串": ("字符串", "子符串"),
    "里奇": ("里奇", "理奇", "Richie", "Ritchie", "ritchie"),
    "丹尼斯": ("丹尼斯", "丹妮斯", "Dennis"),
}


def _subtitle_match_terms(keywords: list[str]) -> list[str]:
    """核心词 + ASR 别名，用于 LIKE / contains。"""
    out: list[str] = []
    seen: set[str] = set()
    for kw in keywords:
        if not kw or len(kw) < 2:
            continue
        variants = _ASR_QUERY_ALIASES.get(kw, (kw,))
        # 也按子串查别名表（如核心词是「数组」嵌在别处）
        for canon, aliases in _ASR_QUERY_ALIASES.items():
            if kw == canon or kw in aliases:
                variants = aliases
                break
        for term in variants:
            key = term.lower()
            if key not in seen:
                seen.add(key)
                out.append(term)
    return out


def _text_has_any(text: str, terms: list[str]) -> list[str]:
    if not text or not terms:
        return []
    low = text.lower()
    hit = []
    for t in terms:
        if t in text or t.lower() in low:
            hit.append(t)
    return hit


def _canon_matched(matched: list[str], query_kws: list[str]) -> list[str]:
    """把 ASR 别名命中折回问题核心词，方便前端与 filter。"""
    out: list[str] = []
    seen: set[str] = set()
    alias_to_canon: dict[str, str] = {}
    for canon, aliases in _ASR_QUERY_ALIASES.items():
        for a in aliases:
            alias_to_canon[a.lower()] = canon
    for m in matched:
        canon = alias_to_canon.get(m.lower(), m)
        # 优先用 query 里的写法
        for q in query_kws:
            if q == canon or q.lower() == canon.lower() or q in _ASR_QUERY_ALIASES.get(canon, ()):
                canon = q
                break
        if canon.lower() not in seen:
            seen.add(canon.lower())
            out.append(canon)
    return out or matched


def _meta_int(meta: dict, key: str) -> int | None:
    val = meta.get(key)
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _scope_video_query(
    q,
    *,
    class_ids: list[int] | None = None,
    course_id: int | None = None,
    agent_id: int | None = None,
    chapter_id: int | None = None,
):
    """给 Material(type=video) 查询加上智能体/班级/课程范围。"""
    if agent_id is not None:
        q = q.where(Material.agent_id == agent_id)
    elif class_ids is not None:
        if not class_ids:
            return None
        q = q.where(Material.class_id.in_(class_ids))
    if chapter_id is not None:
        q = q.where(Material.chapter_id == chapter_id)
    if course_id is not None:
        q = q.join(Chapter, Chapter.id == Material.chapter_id).where(Chapter.course_id == course_id)
    return q


def _video_recs_from_db(
    db: Session,
    keywords: list[str],
    *,
    class_ids: list[int] | None = None,
    course_id: int | None = None,
    agent_id: int | None = None,
    chapter_id: int | None = None,
    max_videos: int = 4,
    core_keywords: list[str] | None = None,
) -> list[dict]:
    """仅用「字幕真正出现关键词」的视频；按匹配强度选最佳时间点。"""
    from ..models import VideoSegment
    from .rag_service import _keyword_specificity

    # 优先用问题原词（如「数组」）；扩展词（numpy）只作字幕辅助，避免乱推
    core = [kw for kw in (core_keywords or keywords) if len(kw) >= 2][:8]
    aux = [
        kw for kw in keywords
        if len(kw) >= 2 and kw not in core and _keyword_specificity(kw) >= 2
    ][:6]
    match_kws = core or [kw for kw in keywords if len(kw) >= 2][:8]
    if not match_kws:
        return []

    core_terms = _subtitle_match_terms(match_kws)
    aux_terms = _subtitle_match_terms(aux)
    seg_kws = list(dict.fromkeys(core_terms + aux_terms))[:20]
    if not seg_kws:
        return []

    seg_q = (
        select(VideoSegment, Material)
        .join(Material, Material.id == VideoSegment.video_id)
        .where(Material.type == "video")
        .where(or_(*[VideoSegment.subtitle_text.contains(kw) for kw in seg_kws]))
    )
    if agent_id is not None:
        seg_q = seg_q.where(Material.agent_id == agent_id)
    elif class_ids is not None:
        if not class_ids:
            return []
        seg_q = seg_q.where(Material.class_id.in_(class_ids))
    if chapter_id is not None:
        seg_q = seg_q.where(Material.chapter_id == chapter_id)
    if course_id is not None:
        seg_q = seg_q.join(Chapter, Chapter.id == Material.chapter_id).where(Chapter.course_id == course_id)

    best_seg: dict[int, tuple[Material, VideoSegment, list[str], float]] = {}
    for seg, mat in db.execute(seg_q.limit(200)).all():
        text = seg.subtitle_text or ""
        matched_core = _text_has_any(text, core_terms)
        if not matched_core:
            title = mat.title or ""
            if not _text_has_any(title, match_kws):
                continue
            matched_core = _text_has_any(text, aux_terms)
            if not matched_core:
                continue
        strength = sum(_keyword_specificity(t) for t in matched_core) + 0.15 * len(matched_core)
        strength -= 0.00005 * float(seg.start_sec or 0)
        prev = best_seg.get(mat.id)
        if prev is None or strength > prev[3]:
            best_seg[mat.id] = (mat, seg, _canon_matched(matched_core, match_kws)[:5], strength)

    if not best_seg:
        return []

    chapters = {
        c.id: c for c in db.scalars(
            select(Chapter).where(Chapter.id.in_([m.chapter_id for m, _, _, _ in best_seg.values()]))
        ).all()
    }
    out: list[dict] = []
    for mid, (mat, seg, matched, strength) in best_seg.items():
        out.append({
            "material_id": mat.id,
            "type": mat.type,
            "title": mat.title,
            "chapter_id": mat.chapter_id,
            "chapter_title": chapters.get(mat.chapter_id).title if chapters.get(mat.chapter_id) else "",
            "score": round(min(0.95, 0.55 + strength * 0.08), 3),
            "video_start_sec": seg.start_sec,
            "video_end_sec": seg.end_sec,
            "page": None,
            "pages": [],
            "keywords": matched,
            "file_url": f"/api/materials/file/{mat.id}",
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:max_videos]


def _aggregate_hits(hits: list[dict]) -> dict[int, dict]:
    """按 material 聚合命中，保留关键词、页码、视频时间点。"""
    by_material: dict[int, dict] = {}
    for h in hits:
        meta = h["metadata"]
        mid = meta.get("material_id")
        if mid is None:
            continue
        mid = int(mid)
        slot = by_material.setdefault(mid, {
            "material_id": mid,
            "chapter_id": int(meta.get("chapter_id", 0)) if meta.get("chapter_id") else None,
            "type": meta.get("type", ""),
            "score": 0.0,
            "video_start_sec": None,
            "video_end_sec": None,
            "page": None,
            "pages": [],
            "keywords": [],
        })
        dist = float(h.get("distance", 1.0))
        slot["score"] = max(slot["score"], 1.0 - dist)
        kw = h.get("keyword", "")
        if kw and kw not in slot["keywords"]:
            slot["keywords"].append(kw)
        start = _meta_int(meta, "start_sec")
        if start is not None:
            end = _meta_int(meta, "end_sec")
            if end is None:
                end = start
            if slot["video_start_sec"] is None or start < slot["video_start_sec"]:
                slot["video_start_sec"] = start
                slot["video_end_sec"] = end
        page = meta.get("page")
        if page and page not in slot["pages"]:
            slot["pages"].append(page)
            if slot["page"] is None:
                slot["page"] = page
    return by_material


def recommend_from_hits(db: Session, hits: list[dict], max_items: int = 12) -> list[dict]:
    """从 RAG 检索结果生成推荐资源列表。"""
    if not hits:
        return []

    # 优先使用排序靠前的命中；不再用 distance<0.1 过滤（会误留泛词 keyword 命中）
    relevant_hits = hits[: max_items * 3]

    by_material = _aggregate_hits(relevant_hits)
    if not by_material:
        return []

    mids = list(by_material.keys())
    materials = db.scalars(select(Material).where(Material.id.in_(mids))).all()
    chapters = {c.id: c for c in db.scalars(select(Chapter).where(
        Chapter.id.in_([m.chapter_id for m in materials])
    )).all()}

    out = []
    for m in materials:
        slot = by_material[m.id]
        pages = sorted(slot["pages"], key=lambda p: int(p) if str(p).isdigit() else 0)
        out.append({
            "material_id": m.id,
            "type": m.type,
            "title": m.title,
            "chapter_id": m.chapter_id,
            "chapter_title": chapters.get(m.chapter_id, None) and chapters[m.chapter_id].title or "",
            "score": round(slot["score"], 3),
            "video_start_sec": slot["video_start_sec"],
            "video_end_sec": slot["video_end_sec"],
            "page": slot["page"],
            "pages": pages[:5],
            "keywords": slot["keywords"][:5],
            "file_url": f"/api/materials/file/{m.id}",
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:max_items]


def ensure_video_recommendations(
    db: Session,
    recommendations: list[dict],
    question: str,
    *,
    chapter_id: int | None = None,
    class_ids: list[int] | None = None,
    course_id: int | None = None,
    agent_id: int | None = None,
    hits: list[dict] | None = None,
    max_videos: int = 4,
    max_items: int = 12,
) -> list[dict]:
    """仅补「字幕中确有问题关键词」的视频，不再用同章硬挂。"""
    if not (question or "").strip():
        return recommendations

    existing_video_ids = {
        r["material_id"] for r in recommendations if r.get("type") == "video"
    }
    if len(existing_video_ids) >= max_videos:
        return recommendations

    from .rag_service import _expand_query_keywords, _extract_keywords

    core = _extract_keywords(question)
    keywords = _expand_query_keywords(question, core)
    video_recs = _video_recs_from_db(
        db, keywords,
        class_ids=class_ids, course_id=course_id,
        agent_id=agent_id, chapter_id=chapter_id,
        max_videos=max_videos, core_keywords=core,
    )
    if not video_recs and chapter_id is not None:
        video_recs = _video_recs_from_db(
            db, keywords,
            class_ids=class_ids, course_id=course_id,
            agent_id=agent_id, chapter_id=None,
            max_videos=max_videos, core_keywords=core,
        )

    extras = [r for r in video_recs if r["material_id"] not in existing_video_ids][:max_videos]
    if not extras:
        return recommendations

    merged = extras + [r for r in recommendations if r.get("type") != "video"]
    for r in recommendations:
        if r.get("type") == "video" and r["material_id"] not in {e["material_id"] for e in extras}:
            merged.insert(len(extras), r)
    return merged[:max_items]


def filter_relevant_recommendations(
    recommendations: list[dict],
    hits: list[dict],
    question: str,
) -> list[dict]:
    """只保留与问题/检索片段真正对应的资料；无证据则返回空（前端不展示「建议学习」）。"""
    from .rag_service import (
        _doc_matches_kw,
        _expand_query_keywords,
        _extract_keywords,
        _keyword_specificity,
    )

    if not recommendations:
        return []

    kws = _expand_query_keywords(question, _extract_keywords(question))
    specific = [k for k in kws if _keyword_specificity(k) >= 1]
    strong = [k for k in specific if _keyword_specificity(k) >= 2]
    if not specific and not hits:
        return []

    hit_mids: set[int] = set()
    hit_docs: dict[int, str] = {}
    for h in hits:
        meta = h.get("metadata") or {}
        mid = meta.get("material_id")
        if mid is None:
            continue
        try:
            mid_i = int(mid)
        except (TypeError, ValueError):
            continue
        hit_mids.add(mid_i)
        hit_docs[mid_i] = (hit_docs.get(mid_i) or "") + "\n" + (h.get("document") or "")

    kept: list[dict] = []
    deferred_videos: list[dict] = []

    def _keep_pdf_like(r: dict) -> bool:
        mid = r.get("material_id")
        title = r.get("title") or ""
        rec_kws = r.get("keywords") or []
        doc = hit_docs.get(mid, "") if mid is not None else ""
        title_hit = any(_doc_matches_kw(title, kw) for kw in strong)
        doc_hit = bool(doc) and any(_doc_matches_kw(doc, kw) for kw in strong)
        # 无强词时退回专项词
        if not strong:
            doc_hit = bool(doc) and any(_doc_matches_kw(doc, kw) for kw in specific)
            title_hit = any(_doc_matches_kw(title, kw) for kw in specific)
        kw_field_hit = any(kw in rec_kws for kw in (strong or specific))
        if mid in hit_mids and (doc_hit or kw_field_hit or title_hit):
            return True
        return False

    for r in recommendations:
        if r.get("type") == "video":
            deferred_videos.append(r)
            continue
        if _keep_pdf_like(r):
            kept.append(r)

    for r in deferred_videos:
        mid = r.get("material_id")
        title = r.get("title") or ""
        rec_kws = r.get("keywords") or []
        doc = hit_docs.get(mid, "") if mid is not None else ""
        core = _extract_keywords(question)
        # 字幕检索写入的 keywords（如「数组」）即可；禁止无字幕证据的同章视频
        subtitle_hit = any(kw in rec_kws for kw in core)
        title_hit = any(_doc_matches_kw(title, kw) for kw in core)
        doc_hit = bool(doc) and any(_doc_matches_kw(doc, kw) for kw in (strong or specific or core))
        if subtitle_hit or doc_hit or (title_hit and mid in hit_mids and doc_hit):
            kept.append(r)
            continue
    return kept


def extract_attachment_keywords(text: str, limit: int = 18) -> list[str]:
    """从试卷/附件正文中提取 C 语言考点关键词，用于在资料库中检索。"""
    from .rag_service import _extract_keywords, _keyword_search  # noqa: F401

    found: list[str] = []
    for term in _C_TOPIC_TERMS:
        if term.lower() in text.lower() or term in text:
            found.append(term)
    for kw in _extract_keywords(text[:10000]):
        if kw not in found and len(kw) >= 2:
            found.append(kw)
    return found[:limit]


def collect_attachment_hits(
    attachments: list,
    class_ids: list[int] | None = None,
    chapter_id: int | None = None,
    course_id: int | None = None,
    agent_id: int | None = None,
) -> list[dict]:
    """仅做 Chroma 关键词命中（无线程不安全的 DB Session），供 asyncio.to_thread 调用。"""
    from .rag_service import _keyword_search

    texts = [getattr(a, "text", "") or a.get("text", "") for a in attachments]
    combined = "\n".join(t for t in texts if t.strip())
    if not combined.strip():
        return []

    keywords = extract_attachment_keywords(combined)
    if not keywords:
        return []

    all_hits: list[dict] = []
    seen: set[str] = set()
    for kw in keywords:
        for h in _keyword_search(
            [kw], chapter_id=chapter_id, class_ids=class_ids, course_id=course_id,
            agent_id=agent_id, limit=8,
        ):
            doc_key = (h.get("document") or "")[:100]
            if doc_key in seen:
                continue
            seen.add(doc_key)
            h = dict(h)
            h["keyword"] = kw
            h["distance"] = 0.0
            all_hits.append(h)
    return all_hits


def recommend_from_attachment(
    db: Session,
    attachments: list,
    class_ids: list[int] | None = None,
    chapter_id: int | None = None,
    course_id: int | None = None,
    max_items: int = 12,
    agent_id: int | None = None,
    question: str = "",
) -> list[dict]:
    """根据附件考点关键词，在资料管理已索引的资源中检索并推荐具体页码/视频时间点。"""
    all_hits = collect_attachment_hits(
        attachments,
        class_ids=class_ids,
        chapter_id=chapter_id,
        course_id=course_id,
        agent_id=agent_id,
    )
    if not all_hits:
        return []

    recs = recommend_from_hits(db, all_hits, max_items=max_items)
    search_q = question or " ".join(
        sorted({(h.get("keyword") or "") for h in all_hits if h.get("keyword")})[:6]
    )
    recs = ensure_video_recommendations(
        db, recs, search_q,
        chapter_id=chapter_id, class_ids=class_ids,
        course_id=course_id, agent_id=agent_id, hits=all_hits, max_items=max_items,
    )
    return filter_relevant_recommendations(recs, all_hits, search_q)


def format_for_prompt(recommendations: list[dict]) -> str:
    """将推荐资源格式化为 prompt 片段，约束模型只引用资料库中的具体资源。"""
    if not recommendations:
        return (
            "（资料库中未检索到与问题直接对应的已上传资源。"
            "请勿编造「建议学习」清单；可基于通识回答，并说明资料库暂无匹配条目。"
            "若需要，建议教师在「资料管理」中补充相关 PDF/PPT/视频后重新索引。）"
        )
    lines = []
    for i, r in enumerate(recommendations, 1):
        loc = r.get("chapter_title") or f"章节{r.get('chapter_id', '')}"
        pages = r.get("pages") or ([r["page"]] if r.get("page") else [])
        if pages:
            loc += f" PDF第{'、'.join(str(p) for p in pages)}页"
        if r.get("video_start_sec") is not None:
            loc += f" 视频{r['video_start_sec']}秒起"
        kws = r.get("keywords") or []
        kw_hint = f"（匹配考点：{'、'.join(kws)}）" if kws else ""
        lines.append(f"[{i}] 《{r['title']}》[{r['type']}] {loc}{kw_hint}")
    return "\n".join(lines)


def recommend_by_question(
    db: Session,
    question: str,
    chapter_id: int | None = None,
    k: int = 5,
    class_ids: list[int] | None = None,
    course_id: int | None = None,
    agent_id: int | None = None,
) -> list[dict]:
    """基于问题生成推荐资源。使用混合检索（关键词+向量），并补充相关视频。"""
    from .rag_service import retrieve
    hits = retrieve(
        question, chapter_id=chapter_id, k=k, class_ids=class_ids,
        course_id=course_id, agent_id=agent_id,
    )
    recs = recommend_from_hits(db, hits)
    recs = ensure_video_recommendations(
        db, recs, question,
        chapter_id=chapter_id, class_ids=class_ids,
        course_id=course_id, agent_id=agent_id, hits=hits,
    )
    return filter_relevant_recommendations(recs, hits, question)
