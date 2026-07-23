"""学生薄弱点解析：汇总其所有课程考核报告中的薄弱点（可辅以错题 KP）。"""
from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Chapter,
    ChapterProgress,
    Exam,
    ExamQuestion,
    ExamReport,
    KnowledgePoint,
    User,
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip().lower())


def resolve_student_weak_targets(
    db: Session,
    user: User,
    *,
    course_id: int | None = None,
    agent_id: int | None = None,
    recent_exam_limit: int = 50,
    all_courses: bool = True,
) -> list[dict]:
    """返回 [{chapter_id, kp_name, weight}]。

    默认汇总该学生**所有课程**已提交考核报告中的 weak_points；
    仅当 all_courses=False 且传入 course_id 时按单课过滤。
    """
    weights: dict[tuple[int | None, str], float] = defaultdict(float)

    exam_q = (
        select(Exam)
        .where(Exam.user_id == user.id, Exam.status == "submitted")
        .order_by(Exam.id.desc())
        .limit(recent_exam_limit)
    )
    exams = list(db.scalars(exam_q).all())
    if not all_courses and course_id is not None:
        chapter_ids = set(
            db.scalars(select(Chapter.id).where(Chapter.course_id == course_id)).all()
        )
        exams = [e for e in exams if e.chapter_id in chapter_ids]

    for exam in exams:
        report = db.scalar(select(ExamReport).where(ExamReport.exam_id == exam.id))
        if report and isinstance(report.weak_points, list):
            for wp in report.weak_points:
                name = str(wp).strip()
                if name:
                    # 报告薄弱点权重最高
                    weights[(exam.chapter_id, name)] += 4.0
        wrong = db.scalars(
            select(ExamQuestion).where(
                ExamQuestion.exam_id == exam.id,
                ExamQuestion.is_correct.is_(False),
            )
        ).all()
        for q in wrong:
            if q.kp_name and q.kp_name.strip():
                weights[(exam.chapter_id, q.kp_name.strip())] += 1.5

    # 全课知识点目录（对齐报告文案到标准化 KP 名）；all_courses 时不限课程
    catalog: list[tuple[int, str]] = []
    kp_q = select(KnowledgePoint)
    if not all_courses and course_id is not None:
        kp_q = kp_q.join(Chapter).where(Chapter.course_id == course_id)
        if agent_id is not None:
            from .chapter_sync import requires_agent_scoped_chapters

            if requires_agent_scoped_chapters(db, course_id, agent_id):
                kp_q = kp_q.where(
                    (Chapter.agent_id == agent_id) | (Chapter.agent_id.is_(None))
                )
    for kp in db.scalars(kp_q).all():
        catalog.append((kp.chapter_id, kp.name))

    aligned: dict[tuple[int | None, str], float] = defaultdict(float)
    for (ch_id, raw), w in weights.items():
        raw_n = _norm(raw)
        matched = False
        for c_id, kp_name in catalog:
            if ch_id is not None and c_id != ch_id:
                continue
            kn = _norm(kp_name)
            if not kn:
                continue
            if kn in raw_n or raw_n in kn:
                aligned[(c_id, kp_name)] += w
                matched = True
        if not matched and raw.strip():
            # 保留报告原文薄弱点（跨课程总结场景）
            aligned[(ch_id, raw.strip())] += w

    if not aligned:
        progress = db.scalars(
            select(ChapterProgress).where(
                ChapterProgress.user_id == user.id,
                ChapterProgress.status != "已完成",
            )
        ).all()
        unfinished = {p.chapter_id for p in progress}
        if not all_courses and course_id is not None:
            unfinished &= set(
                db.scalars(select(Chapter.id).where(Chapter.course_id == course_id)).all()
            )
        for c_id, kp_name in catalog:
            if unfinished and c_id not in unfinished:
                continue
            aligned[(c_id, kp_name)] += 1.0
            if len(aligned) >= 12:
                break

    out = [
        {"chapter_id": ch_id, "kp_name": name, "weight": w}
        for (ch_id, name), w in aligned.items()
        if name
    ]
    out.sort(key=lambda x: -x["weight"])
    return out[:30]
