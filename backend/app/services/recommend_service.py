"""资源推荐服务：基于检索命中的 chunk 反查 materials + chapters，
对视频 chunk 返回精准时间戳，实现「定位视频时间对应知识点」。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chapter, Material
from . import vector_store

# C 语言常见考点词，用于从试卷附件中提取检索关键词
_C_TOPIC_TERMS = (
    "指针", "数组", "函数", "递归", "字符串", "字符数组", "二维数组", "行指针",
    "strcmp", "strlen", "strcpy", "extern", "static", "宏定义", "define",
    "sizeof", "作用域", "存储类别", "全局变量", "局部变量", "形参", "实参",
    "回文", "子串", "进制", "二进制", "gets", "scanf", "printf",
    "自增", "自减", "屏蔽", "传值", "传址", "地址", "偏移",
)


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
        if meta.get("start_sec"):
            s = int(meta["start_sec"])
            e = int(meta.get("end_sec", s))
            if slot["video_start_sec"] is None or s < slot["video_start_sec"]:
                slot["video_start_sec"] = s
                slot["video_end_sec"] = e
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

    relevant_hits = [h for h in hits if float(h.get("distance", 1.0)) < 0.1]
    if not relevant_hits:
        relevant_hits = hits[: max_items * 2]

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


def recommend_from_attachment(
    db: Session,
    attachments: list,
    class_ids: list[int] | None = None,
    chapter_id: int | None = None,
    max_items: int = 12,
) -> list[dict]:
    """根据附件考点关键词，在资料管理已索引的资源中检索并推荐具体页码/视频时间点。"""
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
        for h in _keyword_search([kw], chapter_id=chapter_id, class_ids=class_ids, limit=8):
            doc_key = (h.get("document") or "")[:100]
            if doc_key in seen:
                continue
            seen.add(doc_key)
            h = dict(h)
            h["keyword"] = kw
            h["distance"] = 0.0
            all_hits.append(h)

    return recommend_from_hits(db, all_hits, max_items=max_items)


def format_for_prompt(recommendations: list[dict]) -> str:
    """将推荐资源格式化为 prompt 片段，约束模型只引用资料库中的具体资源。"""
    if not recommendations:
        return (
            "（资料库中未检索到与附件考点匹配的已上传资源。"
            "请如实说明暂无匹配资料，并建议教师在「资料管理」中补充相关 PDF/PPT/视频后重新索引。）"
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
) -> list[dict]:
    """基于问题生成推荐资源。使用混合检索（关键词+向量）。"""
    from .rag_service import retrieve
    hits = retrieve(question, chapter_id=chapter_id, k=k, class_ids=class_ids)
    return recommend_from_hits(db, hits)
