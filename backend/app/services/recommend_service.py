"""资源推荐服务：基于检索命中的 chunk 反查 materials + chapters，
对视频 chunk 返回精准时间戳，实现「定位视频时间对应知识点」。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chapter, Material
from . import vector_store


def recommend_from_hits(db: Session, hits: list[dict]) -> list[dict]:
    """从 RAG 检索结果生成推荐资源列表。"""
    if not hits:
        return []

    # 聚合每个 material 的命中信息
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
        })
        slot["score"] = max(slot["score"], 1.0 - float(h.get("distance", 1.0)))
        # 视频时间戳：取命中的最早 start_sec
        if meta.get("start_sec"):
            s = int(meta["start_sec"]); e = int(meta.get("end_sec", s))
            if slot["video_start_sec"] is None or s < slot["video_start_sec"]:
                slot["video_start_sec"] = s
                slot["video_end_sec"] = e
        if meta.get("page") and slot["page"] is None:
            slot["page"] = meta["page"]

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
            "file_url": f"/api/materials/file/{m.id}",
        })
    # 按相关度排序
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def recommend_by_question(db: Session, question: str, chapter_id: int | None = None, k: int = 5) -> list[dict]:
    hits = vector_store.query(question, n_results=k, where={"chapter_id": str(chapter_id)} if chapter_id else None)
    return recommend_from_hits(db, hits)
