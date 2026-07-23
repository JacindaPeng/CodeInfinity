"""从章节资料（知识库）自动生成考核知识点建议。

优先级：
1. 题库管理中该章节已有题目（含已关联知识点）
2. 资料管理中该章节单独上传的资料（课件/PPT 等，非整本教材）
3. 资料管理中整本教材拆分后的该章节片段
"""
from __future__ import annotations

import json
import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Agent, Chapter, KnowledgePoint, Material, QuestionBank, User
from .agent_access import (
    apply_agent_content_scope,
    is_adopted_snapshot,
    resolve_agent_for_exam,
    resolve_bank_class_ids,
    resolve_resource_class_ids_for_agent,
)
from .exam_service import _run_sync
from .llm_provider import get_provider
from .rag_service import _build_context
from . import vector_store


def _parse_json_array(raw: str) -> list[str]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            start = text.index("[")
            end = text.rindex("]") + 1
            data = json.loads(text[start:end])
        except Exception:
            return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in data:
        name = str(item).strip() if not isinstance(item, dict) else str(item.get("name", "")).strip()
        if not name or len(name) > 64:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _existing_kp_names(
    db: Session,
    chapter_id: int,
    class_ids: list[int],
    agent: Agent | None,
) -> set[str]:
    kp_q = select(KnowledgePoint.name).where(KnowledgePoint.chapter_id == chapter_id)
    if agent and is_adopted_snapshot(agent):
        kp_q = kp_q.where(or_(
            KnowledgePoint.agent_id == agent.id,
            KnowledgePoint.class_id.in_(class_ids),
        ))
    else:
        kp_q = kp_q.where(KnowledgePoint.class_id.in_(class_ids))
    rows = db.scalars(kp_q).all()
    return {r.strip().lower() for r in rows if r}


def _textbook_file_paths(db: Session, course_id: int) -> set[str]:
    """整本教材：同一 PDF 路径被 ≥3 个章节资料引用。"""
    paths = db.scalars(
        select(Material.file_path)
        .join(Chapter, Chapter.id == Material.chapter_id)
        .where(Chapter.course_id == course_id, Material.type == "pdf")
        .distinct()
    ).all()
    out: set[str] = set()
    for fp in paths:
        if not fp:
            continue
        cnt = db.scalar(
            select(func.count()).select_from(Material).where(
                Material.file_path == fp,
                Material.type == "pdf",
            )
        ) or 0
        if cnt >= 3:
            out.add(fp)
    return out


def _list_chapter_materials(
    db: Session,
    chapter: Chapter,
    class_id: int,
    agent: Agent | None,
    agent_id: int | None,
    user: User,
    *,
    textbook: bool,
) -> list[Material]:
    allowed = resolve_resource_class_ids_for_agent(db, user, class_id, agent_id=agent_id)
    mq = select(Material).where(Material.chapter_id == chapter.id)
    mq = apply_agent_content_scope(Material, mq, agent, allowed, db=db)
    if mq is None:
        return []
    materials = db.scalars(mq).all()
    tb_paths = _textbook_file_paths(db, chapter.course_id)
    if textbook:
        return [m for m in materials if m.file_path in tb_paths]
    return [m for m in materials if m.file_path not in tb_paths]


def _fetch_hits_by_materials(material_ids: list[int], limit_per: int = 12) -> list[dict]:
    if not material_ids:
        return []
    col = vector_store.get_collection()
    hits: list[dict] = []
    seen: set[str] = set()
    for mid in material_ids:
        try:
            res = col.get(where={"material_id": str(mid)}, limit=limit_per)
        except Exception:
            continue
        for doc, meta, id_ in zip(
            res.get("documents") or [],
            res.get("metadatas") or [],
            res.get("ids") or [],
        ):
            if not doc or id_ in seen:
                continue
            seen.add(id_)
            hits.append({"document": doc, "metadata": meta or {}, "distance": 0.0})
    return hits


def _gather_question_bank_context(
    db: Session,
    chapter_id: int,
    bank_class_ids: list[int],
    agent: Agent | None,
) -> tuple[str, list[str], int]:
    q = select(QuestionBank).where(QuestionBank.chapter_id == chapter_id)
    if agent and is_adopted_snapshot(agent):
        q = q.where(or_(
            QuestionBank.agent_id == agent.id,
            QuestionBank.class_id.in_(bank_class_ids),
        ))
    else:
        q = q.where(QuestionBank.class_id.in_(bank_class_ids))
    rows = db.scalars(q.order_by(QuestionBank.id)).all()
    if not rows:
        return "", [], 0

    kp_ids = [r.kp_id for r in rows if r.kp_id]
    kp_map: dict[int, str] = {}
    if kp_ids:
        for kp in db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(kp_ids))).all():
            kp_map[kp.id] = kp.name

    direct_names = list(dict.fromkeys(kp_map.values()))
    lines: list[str] = []
    for r in rows[:40]:
        kp_name = kp_map.get(r.kp_id, "") if r.kp_id else ""
        tag = f"（知识点：{kp_name}）" if kp_name else ""
        lines.append(f"- [{r.type}]{tag} {r.stem[:220]}")
        if r.analysis:
            lines.append(f"  解析：{r.analysis[:180]}")
    return "\n".join(lines), direct_names, len(rows)


def _llm_suggest_from_context(
    chapter: Chapter,
    context: str,
    source: str,
    extra_hint: str = "",
) -> list[str]:
    source_desc = {
        "question_bank": "题库中该章节已有题目",
        "chapter_materials": "该章节单独上传的资料（课件/PPT/PDF 等）",
        "textbook": "整本教材中该章节对应片段",
    }.get(source, "课程资料")

    prompt = f"""你是课程教学助手。请根据下方章节信息与「{source_desc}」内容，提取适合作为章节考核的知识点名称。

章节：{chapter.title}
章节描述：{chapter.description or "（无）"}
{extra_hint}

【参考内容】
{context}

要求：
1. 提取 5-12 个具体、可考核的知识点（短语，2-15 个汉字为宜）
2. 知识点必须能在参考内容中找到依据，不要编造未出现的内容
3. 严格输出 JSON 字符串数组，例如 ["变量定义", "循环结构"]
4. 只输出 JSON，不要 markdown 代码块或任何解释
"""
    provider = get_provider()
    raw = _run_sync(provider, [{"role": "user", "content": prompt}])
    return _parse_json_array(raw)


def suggest_knowledge_points(
    db: Session,
    user: User,
    chapter_id: int,
    class_id: int,
    agent_id: int | None = None,
) -> dict:
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise ValueError("章节不存在")

    agent = resolve_agent_for_exam(db, user, class_id, chapter.course_id, agent_id)
    bank_class_ids = resolve_bank_class_ids(db, agent, class_id)
    existing = _existing_kp_names(db, chapter_id, bank_class_ids, agent)

    qb_context, qb_kp_names, qb_count = _gather_question_bank_context(
        db, chapter_id, bank_class_ids, agent,
    )

    source = "empty"
    context = ""
    chunk_count = 0
    suggestions: list[str] = []

    if qb_kp_names:
        source = "question_bank"
        suggestions = list(qb_kp_names)
        if qb_context:
            extra = _llm_suggest_from_context(
                chapter, qb_context, "question_bank",
                extra_hint="题库题目已关联部分知识点，请补充提炼其他考点。",
            )
            seen = {n.lower() for n in suggestions}
            for n in extra:
                if n.lower() not in seen:
                    seen.add(n.lower())
                    suggestions.append(n)
    elif qb_context:
        source = "question_bank"
        suggestions = _llm_suggest_from_context(chapter, qb_context, "question_bank")
    else:
        cw_materials = _list_chapter_materials(
            db, chapter, class_id, agent, agent_id, user, textbook=False,
        )
        hits = _fetch_hits_by_materials([m.id for m in cw_materials])
        if hits:
            source = "chapter_materials"
            context = _build_context(hits)
            chunk_count = len(hits)
            suggestions = _llm_suggest_from_context(chapter, context, "chapter_materials")
        else:
            tb_materials = _list_chapter_materials(
                db, chapter, class_id, agent, agent_id, user, textbook=True,
            )
            hits = _fetch_hits_by_materials([m.id for m in tb_materials])
            if hits:
                source = "textbook"
                context = _build_context(hits)
                chunk_count = len(hits)
                suggestions = _llm_suggest_from_context(chapter, context, "textbook")
            else:
                fallback: list[str] = []
                if chapter.description:
                    parts = re.split(r"[；;。.\n]", chapter.description)
                    fallback = [p.strip() for p in parts if 2 <= len(p.strip()) <= 20][:8]
                return {
                    "suggestions": [n for n in fallback if n.lower() not in existing],
                    "existing": sorted(existing),
                    "source": "chapter_desc" if fallback else "empty",
                    "chunk_count": 0,
                    "question_count": 0,
                }

    return {
        "suggestions": [n for n in suggestions if n.lower() not in existing],
        "existing": sorted(existing),
        "source": source,
        "chunk_count": chunk_count,
        "question_count": qb_count,
    }
