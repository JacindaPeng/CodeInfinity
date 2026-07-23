"""从整本教材 PDF 同步章节到数据库（动态课程如 Java/Python）。"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models import Agent, Chapter, Course, Exam, ExamConfig, ExamQuestion, ExamReport, KnowledgePoint, Material, QuestionBank, ChapterProgress, TeachingClass
from .chapter_splitter import extract_chapter_definitions_from_pdf

# 种子数据中 C 语言课程固定为 id=1，预置章节仅归属原智能体
C_LANG_COURSE_ID = 1
ORIGINAL_C_LANG_SLUG = "c-lang"


def resolve_original_c_lang_agent_id(db: Session) -> int | None:
    """course_id=1 上 id 最小的智能体为预置 C 语言智能体（种子数据）。"""
    return db.scalar(
        select(Agent.id).where(Agent.course_id == C_LANG_COURSE_ID).order_by(Agent.id).limit(1)
    )


def is_original_c_lang_agent(db: Session, agent: Agent | None) -> bool:
    if not agent or agent.course_id != C_LANG_COURSE_ID:
        return False
    original_id = resolve_original_c_lang_agent_id(db)
    return original_id is not None and agent.id == original_id


def uses_course_level_preset_chapters(db: Session, course_id: int, agent_id: int | None) -> bool:
    """C 语言课程中仅原智能体使用课程级预置章节；无 agent 上下文时视为预置（兼容）。"""
    if course_id != C_LANG_COURSE_ID:
        return False
    if agent_id is None:
        return True
    agent = db.get(Agent, agent_id)
    return is_original_c_lang_agent(db, agent)


def requires_agent_scoped_chapters(db: Session, course_id: int, agent_id: int | None) -> bool:
    """是否按智能体隔离章节/资料（含新建 C 语言智能体）。"""
    if course_id == C_LANG_COURSE_ID:
        return not uses_course_level_preset_chapters(db, course_id, agent_id)
    return True


def agent_scoped_chapter_condition(db: Session, course_id: int, agent_id: int):
    """非预置智能体的章节过滤。C 语言新建智能体严禁回落到课程预置章节。"""
    if course_id == C_LANG_COURSE_ID:
        return Chapter.agent_id == agent_id
    mat_ch = select(Material.chapter_id).where(Material.agent_id == agent_id).distinct()
    bank_ch = select(QuestionBank.chapter_id).where(QuestionBank.agent_id == agent_id).distinct()
    return or_(
        Chapter.agent_id == agent_id,
        and_(
            Chapter.agent_id.is_(None),
            or_(Chapter.id.in_(mat_ch), Chapter.id.in_(bank_ch)),
        ),
    )


def _chapter_dicts(chapters: list[Chapter]) -> list[dict[str, Any]]:
    return [{"id": c.id, "title": c.title, "order_idx": c.order_idx} for c in chapters]


def assert_teacher_can_manage_course(db: Session, user, course_id: int) -> None:
    """教师需拥有该课程智能体，或管理该课程下的班级。"""
    if user.role == "admin":
        return
    if user.role != "teacher":
        raise HTTPException(403, "无权操作")
    if db.scalar(
        select(Agent.id).where(Agent.course_id == course_id, Agent.owner_id == user.id).limit(1)
    ):
        return
    from ..deps import get_managed_class_ids

    managed = get_managed_class_ids(db, user)
    if managed and db.scalar(
        select(TeachingClass.id).where(
            TeachingClass.id.in_(managed),
            TeachingClass.course_id == course_id,
        ).limit(1)
    ):
        return
    raise HTTPException(403, "无权管理该课程的章节")


def create_custom_chapters(
    db: Session,
    course_id: int,
    definitions: list[dict[str, Any]],
    *,
    agent_id: int | None = None,
    commit: bool = True,
) -> list[dict[str, Any]]:
    """手动创建章节结构（无整本教材 PDF 时）。"""
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(404, "课程不存在")
    if uses_course_level_preset_chapters(db, course_id, agent_id):
        raise HTTPException(400, "C 语言课程使用预置章节，无需自定义")

    exist_q = select(Chapter.id).where(Chapter.course_id == course_id)
    if agent_id is not None:
        exist_q = exist_q.where(Chapter.agent_id == agent_id)
    if db.scalars(exist_q.limit(1)).first():
        raise HTTPException(400, "该智能体下已有章节，无法重复创建。如需调整请先重置章节结构。")

    if not definitions:
        raise HTTPException(400, "请至少添加一个章节")

    created: list[Chapter] = []
    for i, d in enumerate(definitions):
        title = (d.get("title") or "").strip()
        if not title:
            raise HTTPException(400, f"第 {i + 1} 个章节标题不能为空")
        if len(title) > 128:
            raise HTTPException(400, f"章节标题过长：{title[:20]}…")
        ch = Chapter(
            course_id=course_id,
            agent_id=agent_id,
            title=title,
            order_idx=int(d.get("order_idx") or i + 1),
            description=(d.get("description") or "").strip(),
        )
        db.add(ch)
        db.flush()
        created.append(ch)

    if commit:
        db.commit()
    else:
        db.flush()
    return _chapter_dicts(created)


def resolve_chapters_for_textbook(
    db: Session,
    course_id: int,
    pages_text: list[str],
    agent_id: int | None = None,
    page_corners: list[str] | None = None,
    toc_page_start: int | None = None,
    toc_page_end: int | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """为整本教材上传解析章节列表。

    - C 语言等已有章节课程：直接使用 DB 章节（课程级共享）
    - Java/Python 等：按智能体隔离章节；从 PDF 分析并写入 chapters 表

    返回 (chapter_dicts, chapters_created)
    """
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(404, "课程不存在")

    exist_q = select(Chapter).where(Chapter.course_id == course_id)
    if uses_course_level_preset_chapters(db, course_id, agent_id):
        exist_q = exist_q.where(Chapter.agent_id.is_(None))
    elif requires_agent_scoped_chapters(db, course_id, agent_id) and agent_id is not None:
        exist_q = exist_q.where(Chapter.agent_id == agent_id)
    existing = db.scalars(exist_q.order_by(Chapter.order_idx, Chapter.id)).all()

    if existing:
        return _chapter_dicts(existing), False

    if uses_course_level_preset_chapters(db, course_id, agent_id):
        raise HTTPException(400, "C 语言课程章节未初始化，请先运行数据库初始化脚本")

    if agent_id is None:
        raise HTTPException(400, "动态课程上传教材需指定智能体，请从课程智能体上下文进入并上传")

    definitions = extract_chapter_definitions_from_pdf(
        pages_text,
        page_corners=page_corners,
        toc_page_start=toc_page_start,
        toc_page_end=toc_page_end,
    )
    if not definitions:
        raise HTTPException(
            400,
            "未能从 PDF 识别章节结构。请确认教材含「第N章」格式目录或章节标题；"
            "若目录位置特殊，可填写「目录页码」后再试。",
        )

    created: list[Chapter] = []
    for d in definitions:
        ch = Chapter(
            course_id=course_id,
            agent_id=agent_id,
            title=d["title"],
            order_idx=d["order_idx"],
            description=d.get("subtitle") or "",
        )
        db.add(ch)
        db.flush()
        created.append(ch)

    db.flush()
    return _chapter_dicts(created), True


def cleanup_placeholder_chapters(db: Session) -> int:
    """删除 Java/Python 等课程的无资料占位章节（迁移用）。"""
    removed = 0
    for course_name in ("Java程序设计", "Python程序设计"):
        course = db.scalar(select(Course).where(Course.name == course_name))
        if not course:
            continue
        chapters = db.scalars(
            select(Chapter).where(Chapter.course_id == course.id)
        ).all()
        if not chapters:
            continue
        ch_ids = [c.id for c in chapters]
        has_material = db.scalar(
            select(Material.id).where(Material.chapter_id.in_(ch_ids)).limit(1)
        )
        if has_material:
            continue
        for ch in chapters:
            db.delete(ch)
            removed += 1
    if removed:
        db.commit()
    return removed


def reset_dynamic_course(
    db: Session,
    course_id: int,
    *,
    agent_id: int | None = None,
    set_agent_planned: bool = True,
) -> dict:
    """重置动态课程（Java/Python）的章节与资料，可选将智能体恢复为筹备中。

    不影响 C 语言课程（course_id=1）。agent_id 指定时仅重置该智能体下的章节。
    """
    if uses_course_level_preset_chapters(db, course_id, agent_id):
        raise HTTPException(400, "不能重置 C 语言课程预置数据")

    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(404, "课程不存在")

    ch_q = select(Chapter).where(Chapter.course_id == course_id)
    if agent_id is not None:
        ch_q = ch_q.where(Chapter.agent_id == agent_id)
    chapters = db.scalars(ch_q).all()
    ch_ids = [c.id for c in chapters]
    if not ch_ids:
        if set_agent_planned and agent_id is not None:
            agent = db.get(Agent, agent_id)
            if agent and agent.status != "planned":
                agent.status = "planned"
        elif set_agent_planned:
            agent = db.scalar(select(Agent).where(Agent.course_id == course_id))
            if agent and agent.status != "planned":
                agent.status = "planned"
        db.commit()
        return {"chapters_removed": 0, "materials_removed": 0, "agent_status": "planned" if set_agent_planned else None}

    from . import vector_store

    materials = db.scalars(select(Material).where(Material.chapter_id.in_(ch_ids))).all()
    file_paths: set[str] = set()
    for m in materials:
        vector_store.delete_by_material(m.id)
        file_paths.add(m.file_path)
        db.delete(m)

    exams = db.scalars(select(Exam).where(Exam.chapter_id.in_(ch_ids))).all()
    for ex in exams:
        for q in list(ex.questions):
            db.delete(q)
        if ex.report:
            db.delete(ex.report)
        db.delete(ex)

    for model in (ExamConfig, QuestionBank, KnowledgePoint, ChapterProgress):
        rows = db.scalars(select(model).where(model.chapter_id.in_(ch_ids))).all()
        for row in rows:
            db.delete(row)

    for ch in chapters:
        db.delete(ch)

    if set_agent_planned:
        if agent_id is not None:
            agent = db.get(Agent, agent_id)
            if agent:
                agent.status = "planned"
        else:
            agent = db.scalar(select(Agent).where(Agent.course_id == course_id))
            if agent:
                agent.status = "planned"

    db.commit()

    import os
    for fp in file_paths:
        if not db.scalar(select(Material.id).where(Material.file_path == fp).limit(1)):
            try:
                if os.path.exists(fp):
                    os.unlink(fp)
            except OSError:
                pass

    return {
        "chapters_removed": len(chapters),
        "materials_removed": len(materials),
        "agent_status": "planned" if set_agent_planned else None,
    }
