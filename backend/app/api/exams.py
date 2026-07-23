"""考核路由：学生端开始/答题/交卷/报告 + 教师端配置/题库/知识点/学生记录。

路由顺序：具体路径（/start, /history/*, /teacher/*, /config/*, /bank/*, /knowledge-points/*）
必须定义在 /{exam_id} 通配之前，避免被 {exam_id} 抢占匹配。
"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sse_starlette.sse import EventSourceResponse

from ..deps import (
    CurrentUser,
    DBSession,
    require_role,
    resolve_teacher_scope,
    assert_teacher_can_view_student,
    assert_can_access_question,
    assert_teacher_upload_class,
    assert_teacher_manages_class,
    resolve_resource_class_ids,
    resolve_config_class_id,
    get_exam_config,
    get_managed_class_ids,
    get_class_student_ids,
    log_call,
)
from ..models import (
    Agent,
    Chapter,
    Exam,
    ExamConfig,
    ExamIntervention,
    ExamQuestion,
    ExamReport,
    KnowledgePoint,
    Material,
    QuestionBank,
    TeachingClass,
    User,
)
from ..services.chapter_sync import (
    C_LANG_COURSE_ID,
    requires_agent_scoped_chapters,
    uses_course_level_preset_chapters,
    agent_scoped_chapter_condition,
)
from ..services.enrollment import get_student_class_for_course
from ..services import exam_service, exam_feedback_service, kp_suggest_service
from ..services.agent_access import (
    apply_agent_content_scope,
    get_shared_exam_config,
    is_adopted_snapshot,
    resolve_agent_for_exam,
    resolve_bank_class_ids,
    resolve_resource_class_ids_for_agent,
)

router = APIRouter(prefix="/exams", tags=["exams"])


# ============ 具体路径（优先匹配） ============

class StartIn(BaseModel):
    chapter_id: int
    class_id: int | None = None  # 教师考核测试时指定班级
    agent_id: int | None = None  # 课程智能体（共享资料/题库）


class GradingFeedbackIn(BaseModel):
    verdict: str  # agree / disagree
    comment: str = ""


@router.post("/start")
def start_exam(payload: StartIn, user: CurrentUser, db: DBSession) -> dict:
    try:
        if user.role == "student":
            chapter = db.get(Chapter, payload.chapter_id)
            if not chapter:
                raise HTTPException(404, "章节不存在")
            exam_class_id = get_student_class_for_course(db, user, chapter.course_id)
            if not exam_class_id:
                raise HTTPException(400, "尚未加入该课程班级，无法开始考核")
            teacher_test = False
        else:
            if not payload.class_id:
                raise HTTPException(400, "请指定班级")
            exam_class_id = resolve_config_class_id(db, user, payload.class_id, agent_id=payload.agent_id)
            teacher_test = True
        exam, warnings = exam_service.generate_paper(
            db, user, payload.chapter_id,
            class_id=exam_class_id,
            teacher_test=teacher_test,
            agent_id=payload.agent_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "exam_id": exam.id,
        "questions": exam_service.exam_to_dict(exam)["questions"],
        "warnings": warnings,
    }


@router.get("/history/mine")
def my_history(
    user: CurrentUser,
    db: DBSession,
    course_id: int | None = Query(default=None),
) -> list[dict]:
    base = select(Exam).where(Exam.user_id == user.id)
    if course_id is not None:
        chapter_ids = db.scalars(
            select(Chapter.id).where(Chapter.course_id == course_id)
        ).all()
        if not chapter_ids:
            return []
        base = base.where(Exam.chapter_id.in_(chapter_ids))
    rows = db.scalars(base.order_by(Exam.id.desc())).all()
    out = []
    for e in rows:
        ch = db.get(Chapter, e.chapter_id)
        report = db.scalar(select(ExamReport).where(ExamReport.exam_id == e.id))
        out.append({
            "id": e.id, "chapter_id": e.chapter_id,
            "chapter_title": ch.title if ch else "",
            "status": e.status,
            "total_score": report.total_score if report else None,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "submitted_at": e.submitted_at.isoformat() if e.submitted_at else None,
        })
    return out


# ---- 教师端：查看所有学生考核记录 ----

@router.get("/teacher/all", dependencies=[Depends(require_role("teacher"))])
def teacher_list_exams(
    user: CurrentUser,
    db: DBSession,
    chapter_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    class_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> dict:
    """教师查看所管班级学生的考核记录（含分数）。"""
    from ..services.agent_access import get_teacher_agent_bound_classes

    if agent_id and user.role == "teacher":
        bound = get_teacher_agent_bound_classes(db, user, agent_id)
        if class_id:
            if class_id not in bound:
                raise HTTPException(403, "该班级未绑定当前智能体")
            _, allowed_students = resolve_teacher_scope(db, user, class_id)
        elif bound:
            allowed_students = get_class_student_ids(db, bound)
        else:
            return {"total": 0, "page": page, "size": size, "items": []}
    else:
        _, allowed_students = resolve_teacher_scope(db, user, class_id)
    if not allowed_students:
        return {"total": 0, "page": page, "size": size, "items": []}
    base = select(Exam).where(Exam.user_id.in_(allowed_students))
    if chapter_id:
        base = base.where(Exam.chapter_id == chapter_id)
    if user_id:
        if user_id not in allowed_students:
            raise HTTPException(403, "无权查看该学生")
        base = base.where(Exam.user_id == user_id)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Exam.id.desc()).offset((page - 1) * size).limit(size)).all()

    items = []
    for e in rows:
        u = db.get(User, e.user_id)
        ch = db.get(Chapter, e.chapter_id)
        report = db.scalar(select(ExamReport).where(ExamReport.exam_id == e.id))
        items.append({
            "id": e.id,
            "user_id": e.user_id,
            "username": u.username if u else "",
            "display_name": u.display_name if u else "",
            "chapter_id": e.chapter_id,
            "chapter_title": ch.title if ch else "",
            "status": e.status,
            "total_score": report.total_score if report else None,
            "has_report": report is not None,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "submitted_at": e.submitted_at.isoformat() if e.submitted_at else None,
        })
    return {"total": total, "page": page, "size": size, "items": items}


@router.get("/teacher/all/{exam_id}/report", dependencies=[Depends(require_role("teacher"))])
def teacher_get_report(exam_id: int, user: CurrentUser, db: DBSession) -> dict:
    """教师查看学生的考核报告。"""
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(404, "考核不存在")
    if exam.user_id != user.id:
        assert_teacher_can_view_student(db, user, exam.user_id)
    elif user.role not in ("teacher", "admin"):
        raise HTTPException(403, "无权查看")
    if exam.status != "submitted":
        raise HTTPException(400, "尚未提交")
    report = db.scalar(select(ExamReport).where(ExamReport.exam_id == exam_id))
    if not report:
        raise HTTPException(404, "报告尚未生成")
    u = db.get(User, exam.user_id)
    ch = db.get(Chapter, exam.chapter_id)
    return {
        "exam_id": exam_id,
        "chapter_id": exam.chapter_id,
        "chapter_title": ch.title if ch else "",
        "student_name": u.display_name if u else "",
        "student_username": u.username if u else "",
        "dimensions": report.dimensions_json,
        "summary": report.summary,
        "suggestions": report.suggestions,
        "total_score": report.total_score,
        "weak_points": report.weak_points or [],
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "questions": exam_service.exam_to_dict(exam)["questions"],
        "feedback_meta": exam_feedback_service.get_report_feedback_meta(
            db, exam, exam.user_id, viewer=user,
        ),
    }


@router.get("/teacher/all/{exam_id}/questions/{idx}/followups", dependencies=[Depends(require_role("teacher", "admin"))])
def teacher_list_question_followups(
    exam_id: int, idx: int, user: CurrentUser, db: DBSession,
) -> list:
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(404, "考核不存在")
    if exam.user_id != user.id:
        assert_teacher_can_view_student(db, user, exam.user_id)
    elif user.role not in ("teacher", "admin"):
        raise HTTPException(403, "无权查看")
    if exam.status != "submitted":
        raise HTTPException(400, "尚未提交")
    return exam_feedback_service.list_followups(db, exam.id, idx, exam.user_id)


@router.post("/teacher/all/{exam_id}/questions/{idx}/grading-feedback", dependencies=[Depends(require_role("teacher", "admin"))])
def teacher_submit_grading_review(
    exam_id: int,
    idx: int,
    payload: GradingFeedbackIn,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(404, "考核不存在")
    if exam.user_id != user.id:
        assert_teacher_can_view_student(db, user, exam.user_id)
    elif user.role not in ("teacher", "admin"):
        raise HTTPException(403, "无权操作")
    if exam.status != "submitted":
        raise HTTPException(400, "尚未提交")
    try:
        return exam_feedback_service.submit_teacher_grading_review(
            db, exam, idx, user, payload.verdict, payload.comment,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---- 教师端：判卷争议介入 ----

@router.get("/teacher/interventions/pending-count", dependencies=[Depends(require_role("teacher"))])
def teacher_intervention_pending_count(user: CurrentUser, db: DBSession) -> dict:
    managed = get_managed_class_ids(db, user) or []
    if not managed:
        return {"count": 0}
    cnt = db.scalar(
        select(func.count()).select_from(ExamIntervention).where(
            ExamIntervention.class_id.in_(managed),
            ExamIntervention.status == "pending",
        )
    ) or 0
    return {"count": cnt}


@router.get("/teacher/interventions", dependencies=[Depends(require_role("teacher"))])
def teacher_list_interventions(
    user: CurrentUser,
    db: DBSession,
    status: str | None = Query(default="pending"),
    class_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict:
    from ..services.agent_access import get_teacher_agent_bound_classes

    managed = get_managed_class_ids(db, user) or []
    if agent_id and user.role == "teacher":
        managed = get_teacher_agent_bound_classes(db, user, agent_id)
    if class_id is not None and class_id not in managed:
        raise HTTPException(403, "无权查看该班级")
    return exam_feedback_service.list_teacher_interventions(
        db, user, managed, status=status, class_id=class_id, page=page, size=size,
    )


@router.get("/teacher/interventions/{iv_id}", dependencies=[Depends(require_role("teacher"))])
def teacher_get_intervention(iv_id: int, user: CurrentUser, db: DBSession) -> dict:
    iv = exam_feedback_service.get_intervention_detail(db, iv_id)
    if not iv:
        raise HTTPException(404, "申请不存在")
    managed = get_managed_class_ids(db, user) or []
    if iv.class_id not in managed:
        raise HTTPException(403, "无权查看")
    exam = db.get(Exam, iv.exam_id)
    student = db.get(User, iv.student_id)
    ch = db.get(Chapter, exam.chapter_id) if exam else None
    resolver = db.get(User, iv.resolved_by) if iv.resolved_by else None
    return {
        "id": iv.id,
        "exam_id": iv.exam_id,
        "question_idx": iv.question_idx,
        "student_id": iv.student_id,
        "student_name": student.display_name if student else "",
        "student_username": student.username if student else "",
        "chapter_title": ch.title if ch else "",
        "class_id": iv.class_id,
        "trigger": iv.trigger,
        "status": iv.status,
        "student_message": iv.student_message,
        "teacher_response": iv.teacher_response,
        "resolved_by_id": iv.resolved_by,
        "resolved_by_name": (resolver.display_name or resolver.username) if resolver else "",
        "context": exam_feedback_service.enrich_intervention_context(db, iv),
        "resolved_score": iv.resolved_score,
        "created_at": iv.created_at.isoformat() if iv.created_at else None,
        "resolved_at": iv.resolved_at.isoformat() if iv.resolved_at else None,
        "report_url": f"/teacher/exams/{iv.exam_id}/report",
    }


class InterventionResolveIn(BaseModel):
    action: str = "resolved"  # 仅支持 resolved
    teacher_response: str = ""
    resolved_score: float | None = None
    student_feedback_correct: bool | None = None


@router.put("/teacher/interventions/{iv_id}", dependencies=[Depends(require_role("teacher"))])
def teacher_resolve_intervention(
    iv_id: int,
    payload: InterventionResolveIn,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    iv = exam_feedback_service.get_intervention_detail(db, iv_id)
    if not iv:
        raise HTTPException(404, "申请不存在")
    assert_teacher_manages_class(db, user, iv.class_id)
    if payload.action != "resolved":
        raise HTTPException(400, "教师只能确认处理介入申请")
    try:
        return exam_feedback_service.resolve_intervention(
            db, iv, user,
            action=payload.action,
            teacher_response=payload.teacher_response,
            resolved_score=payload.resolved_score,
            student_feedback_correct=payload.student_feedback_correct,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/teacher/students", dependencies=[Depends(require_role("teacher"))])
def teacher_list_students(
    user: CurrentUser,
    db: DBSession,
    class_id: int | None = Query(default=None),
) -> list[dict]:
    """列出所管班级内的学生（供筛选下拉用）。"""
    _, allowed_students = resolve_teacher_scope(db, user, class_id)
    if not allowed_students:
        return []
    rows = db.scalars(
        select(User).where(User.id.in_(allowed_students)).order_by(User.id)
    ).all()
    return [{"id": u.id, "username": u.username, "display_name": u.display_name} for u in rows]


# ---- 教师端：考核配置 ----

class ExamConfigIn(BaseModel):
    chapter_id: int
    class_id: int | None = None
    class_ids: list[int] = []
    config: dict
    max_attempts: int = 0  # 0=无限次


def _resolve_class_ids(payload_class_id: int | None, payload_class_ids: list[int]) -> list[int]:
    ids = list(dict.fromkeys(payload_class_ids or ([payload_class_id] if payload_class_id else [])))
    if not ids:
        raise HTTPException(400, "请至少选择一个班级")
    return ids


@router.get("/config/{chapter_id}", dependencies=[Depends(require_role("teacher", "admin"))])
def get_config(
    chapter_id: int,
    user: CurrentUser,
    db: DBSession,
    class_id: int = Query(...),
    agent_id: int | None = Query(default=None),
) -> dict:
    cid = resolve_config_class_id(db, user, class_id, agent_id=agent_id)
    chapter = db.get(Chapter, chapter_id)
    agent = resolve_agent_for_exam(
        db, user, cid, chapter.course_id if chapter else None, agent_id,
    )
    cfg = get_shared_exam_config(db, chapter_id, cid, agent)
    if not cfg:
        return {"chapter_id": chapter_id, "class_id": cid, "config": {}, "max_attempts": 0}
    return {
        "chapter_id": chapter_id,
        "class_id": cid,
        "config": cfg.config_json,
        "max_attempts": cfg.max_attempts,
    }


@router.post("/config", dependencies=[Depends(require_role("teacher", "admin"))])
def upsert_config(payload: ExamConfigIn, user: CurrentUser, db: DBSession) -> dict:
    if not db.get(Chapter, payload.chapter_id):
        raise HTTPException(404, "章节不存在")
    class_ids = _resolve_class_ids(payload.class_id, payload.class_ids)
    for cid in class_ids:
        assert_teacher_upload_class(db, user, cid)
        cfg = get_exam_config(db, payload.chapter_id, cid)
        if cfg:
            cfg.config_json = payload.config
            cfg.max_attempts = payload.max_attempts
        else:
            db.add(ExamConfig(
                chapter_id=payload.chapter_id,
                class_id=cid,
                config_json=payload.config,
                max_attempts=payload.max_attempts,
            ))
    db.commit()
    return {"ok": True, "class_count": len(class_ids)}


# 学生查看某章考核次数与上限；教师预览某班配置
@router.get("/attempts/{chapter_id}")
def get_attempts(
    chapter_id: int,
    user: CurrentUser,
    db: DBSession,
    class_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
) -> dict:
    """返回当前用户在指定章节的考核次数、上限、剩余次数。"""
    chapter = db.get(Chapter, chapter_id)
    if user.role == "student":
        cid = resolve_config_class_id(
            db, user,
            class_id=class_id,
            course_id=chapter.course_id if chapter else None,
        )
    else:
        cid = resolve_config_class_id(db, user, class_id, agent_id=agent_id)
    agent = resolve_agent_for_exam(
        db, user, cid, chapter.course_id if chapter else None, agent_id,
    )
    cfg = get_shared_exam_config(db, chapter_id, cid, agent)
    max_attempts = cfg.max_attempts if cfg else 0
    count = db.scalar(
        select(func.count()).select_from(
            select(Exam).where(
                Exam.user_id == user.id,
                Exam.chapter_id == chapter_id,
            ).subquery()
        )
    ) or 0
    remaining = -1
    if user.role == "student" and max_attempts > 0:
        remaining = max_attempts - count
    return {
        "chapter_id": chapter_id,
        "class_id": cid,
        "configured": cfg is not None,
        "used": count,
        "max": max_attempts,
        "remaining": remaining,
    }


@router.get("/teacher/class-progress", dependencies=[Depends(require_role("teacher", "admin"))])
def teacher_class_progress(
    user: CurrentUser,
    db: DBSession,
    class_id: int = Query(...),
    course_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
) -> dict:
    """教师查看所管班级各章节考核完成率。"""
    resolve_config_class_id(db, user, class_id, agent_id=agent_id)
    _, student_ids = resolve_teacher_scope(db, user, class_id)
    student_count = len(student_ids)
    cq = select(Chapter).order_by(Chapter.order_idx, Chapter.id)
    if course_id is not None:
        cq = cq.where(Chapter.course_id == course_id)
    if course_id is not None and uses_course_level_preset_chapters(db, course_id, agent_id):
        cq = cq.where(Chapter.agent_id.is_(None))
        chapters = db.scalars(cq).all()
    elif course_id is not None and requires_agent_scoped_chapters(db, course_id, agent_id):
        if agent_id is None:
            chapters = []
        else:
            cq = cq.where(agent_scoped_chapter_condition(db, course_id, agent_id))
            chapters = db.scalars(cq).all()
    else:
        chapters = db.scalars(cq).all()
    chapter_stats = []
    for ch in chapters:
        completed_count = 0
        if student_ids:
            completed_count = db.scalar(
                select(func.count(func.distinct(Exam.user_id))).where(
                    Exam.user_id.in_(student_ids),
                    Exam.chapter_id == ch.id,
                    Exam.status == "submitted",
                )
            ) or 0
        rate = round(completed_count / student_count * 100, 1) if student_count else 0.0
        chapter_stats.append({
            "chapter_id": ch.id,
            "chapter_title": ch.title,
            "order_idx": ch.order_idx,
            "completed_count": completed_count,
            "student_count": student_count,
            "completion_rate": rate,
            "configured": get_exam_config(db, ch.id, class_id) is not None,
        })
    cls = db.get(TeachingClass, class_id)
    return {
        "class_id": class_id,
        "class_name": cls.name if cls else "",
        "student_count": student_count,
        "chapters": chapter_stats,
    }


# ---- 教师端：题库 ----

class QuestionIn(BaseModel):
    chapter_id: int
    class_id: int | None = None
    class_ids: list[int] = []
    kp_id: int | None = None
    type: str
    stem: str
    options: list[str] = []
    answer: str
    analysis: str = ""


@router.get("/bank", dependencies=[Depends(require_role("teacher", "admin"))])
def list_bank(
    user: CurrentUser,
    db: DBSession,
    chapter_id: int | None = None,
    class_id: int | None = Query(default=None),
    course_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
) -> list[dict]:
    allowed_classes = resolve_resource_class_ids_for_agent(
        db, user, class_id, agent_id=agent_id,
    )
    agent = db.get(Agent, agent_id) if agent_id else None
    q = select(QuestionBank).order_by(QuestionBank.id.desc())
    if chapter_id:
        q = q.where(QuestionBank.chapter_id == chapter_id)
    if course_id is not None:
        if not requires_agent_scoped_chapters(db, course_id, agent_id):
            chapter_ids = db.scalars(
                select(Chapter.id).where(Chapter.course_id == course_id)
            ).all()
            if not chapter_ids:
                return []
            q = q.where(QuestionBank.chapter_id.in_(chapter_ids))
        elif agent_id is None:
            return []
    q = apply_agent_content_scope(QuestionBank, q, agent, allowed_classes, db=db)
    if q is None:
        return []
    rows = db.scalars(q).all()
    return [
        {
            "id": r.id, "chapter_id": r.chapter_id, "class_id": r.class_id,
            "kp_id": r.kp_id,
            "type": r.type, "stem": r.stem, "options": r.options_json or [],
            "answer": r.answer, "analysis": r.analysis,
        }
        for r in rows
    ]


@router.post("/bank", dependencies=[Depends(require_role("teacher", "admin"))])
def add_bank(payload: QuestionIn, user: CurrentUser, db: DBSession) -> dict:
    if not db.get(Chapter, payload.chapter_id):
        raise HTTPException(404, "章节不存在")
    class_ids = _resolve_class_ids(payload.class_id, payload.class_ids)
    created_ids: list[int] = []
    for cid in class_ids:
        assert_teacher_upload_class(db, user, cid)
        q = QuestionBank(
            chapter_id=payload.chapter_id, class_id=cid, kp_id=payload.kp_id, type=payload.type,
            stem=payload.stem, options_json=payload.options,
            answer=payload.answer, analysis=payload.analysis,
        )
        db.add(q)
        db.flush()
        created_ids.append(q.id)
    db.commit()
    return {"ids": created_ids, "id": created_ids[0] if created_ids else None, "created": len(created_ids)}


@router.put("/bank/{qid}", dependencies=[Depends(require_role("teacher", "admin"))])
def update_bank(qid: int, payload: QuestionIn, user: CurrentUser, db: DBSession) -> dict:
    q = db.get(QuestionBank, qid)
    if not q:
        raise HTTPException(404, "题目不存在")
    assert_can_access_question(db, user, q)
    target_class = payload.class_id
    if not target_class:
        raise HTTPException(400, "请指定班级")
    assert_teacher_upload_class(db, user, target_class)
    q.chapter_id = payload.chapter_id
    q.class_id = target_class
    q.kp_id = payload.kp_id
    q.type = payload.type
    q.stem = payload.stem
    q.options_json = payload.options
    q.answer = payload.answer
    q.analysis = payload.analysis
    db.commit()
    return {"ok": True}


@router.delete("/bank/{qid}", dependencies=[Depends(require_role("teacher", "admin"))])
def delete_bank(qid: int, user: CurrentUser, db: DBSession) -> dict:
    q = db.get(QuestionBank, qid)
    if q:
        assert_can_access_question(db, user, q)
        db.delete(q); db.commit()
    return {"ok": True}


# ---- 知识点 CRUD ----

class KPIn(BaseModel):
    chapter_id: int
    class_id: int | None = None
    class_ids: list[int] = []
    name: str


@router.get("/knowledge-points/{chapter_id}/suggest", dependencies=[Depends(require_role("teacher", "admin"))])
def suggest_kps(
    chapter_id: int,
    user: CurrentUser,
    db: DBSession,
    class_id: int = Query(...),
    agent_id: int | None = Query(default=None),
) -> dict:
    """从章节资料（知识库）自动生成知识点建议，供教师选择性添加。"""
    resolve_config_class_id(db, user, class_id, agent_id=agent_id)
    try:
        return kp_suggest_service.suggest_knowledge_points(
            db, user, chapter_id, class_id, agent_id=agent_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/knowledge-points/{chapter_id}")
def list_kps(
    chapter_id: int,
    user: CurrentUser,
    db: DBSession,
    class_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
) -> list[dict]:
    cid = resolve_config_class_id(db, user, class_id, agent_id=agent_id)
    chapter = db.get(Chapter, chapter_id)
    agent = resolve_agent_for_exam(
        db, user, cid, chapter.course_id if chapter else None, agent_id,
    )
    class_ids = resolve_bank_class_ids(db, agent, cid)
    kp_q = select(KnowledgePoint).where(KnowledgePoint.chapter_id == chapter_id)
    if agent and is_adopted_snapshot(agent):
        kp_q = kp_q.where(or_(
            KnowledgePoint.agent_id == agent.id,
            KnowledgePoint.class_id.in_(class_ids),
        ))
    else:
        kp_q = kp_q.where(KnowledgePoint.class_id.in_(class_ids))
    rows = db.scalars(kp_q).all()
    return [{"id": r.id, "name": r.name} for r in rows]


@router.post("/knowledge-points", dependencies=[Depends(require_role("teacher", "admin"))])
def add_kp(payload: KPIn, user: CurrentUser, db: DBSession) -> dict:
    if not db.get(Chapter, payload.chapter_id):
        raise HTTPException(404, "章节不存在")
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "知识点名称不能为空")
    class_ids = _resolve_class_ids(payload.class_id, payload.class_ids)
    created_ids: list[int] = []
    skipped = 0
    for cid in class_ids:
        assert_teacher_upload_class(db, user, cid)
        existing = db.scalar(
            select(KnowledgePoint).where(
                KnowledgePoint.chapter_id == payload.chapter_id,
                KnowledgePoint.class_id == cid,
                KnowledgePoint.name == name,
            )
        )
        if existing:
            created_ids.append(existing.id)
            skipped += 1
            continue
        kp = KnowledgePoint(
            chapter_id=payload.chapter_id,
            class_id=cid,
            name=name,
        )
        db.add(kp)
        db.flush()
        created_ids.append(kp.id)
    db.commit()
    return {"ids": created_ids, "created": len(created_ids) - skipped, "skipped": skipped}


@router.put("/knowledge-points/{kp_id}", dependencies=[Depends(require_role("teacher", "admin"))])
def update_kp(kp_id: int, payload: KPIn, user: CurrentUser, db: DBSession) -> dict:
    kp = db.get(KnowledgePoint, kp_id)
    if not kp:
        raise HTTPException(404, "知识点不存在")
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "知识点名称不能为空")
    target_class = payload.class_id or kp.class_id
    if not target_class:
        raise HTTPException(400, "请指定班级")
    assert_teacher_upload_class(db, user, target_class)
    kp.chapter_id = payload.chapter_id
    kp.class_id = target_class
    kp.name = name
    db.commit()
    return {"ok": True}


@router.delete("/knowledge-points/{kp_id}", dependencies=[Depends(require_role("teacher", "admin"))])
def delete_kp(kp_id: int, user: CurrentUser, db: DBSession) -> dict:
    kp = db.get(KnowledgePoint, kp_id)
    if kp:
        if kp.class_id:
            assert_teacher_upload_class(db, user, kp.class_id)
        elif user.role != "admin":
            raise HTTPException(status_code=403, detail="无权删除该知识点")
        db.delete(kp); db.commit()
    return {"ok": True}


# ============ {exam_id} 通配路径（放最后） ============

class AnswerIn(BaseModel):
    idx: int
    answer: str


@router.post("/{exam_id}/answer")
def save_answer(exam_id: int, payload: AnswerIn, user: CurrentUser, db: DBSession) -> dict:
    exam = db.get(Exam, exam_id)
    if not exam or exam.user_id != user.id:
        raise HTTPException(404, "考核不存在")
    if exam.status == "submitted":
        raise HTTPException(400, "考核已提交")
    exam_service.save_answer(db, exam, payload.idx, payload.answer)
    return {"ok": True}


@router.post("/{exam_id}/submit")
def submit_exam(exam_id: int, user: CurrentUser, db: DBSession) -> dict:
    exam = db.get(Exam, exam_id)
    if not exam or exam.user_id != user.id:
        raise HTTPException(404, "考核不存在")
    if exam.status == "submitted":
        raise HTTPException(400, "考核已提交")
    exam = exam_service.grade_exam(db, exam)
    # generate_report 可能因 LLM 调用失败或数据类型问题而抛异常，用降级报告兜底
    try:
        report = exam_service.generate_report(db, exam)
    except Exception as e:
        # 必须先 rollback，否则 session 处于 PendingRollbackError 状态
        db.rollback()
        # 重新获取 exam（rollback 后对象可能过期）
        exam = db.get(Exam, exam_id)
        report = exam_service.generate_fallback_report(db, exam, str(e))
    return {"exam_id": exam.id, "report_id": report.id, "total_score": report.total_score}


@router.post("/{exam_id}/regenerate-report")
def regenerate_report(exam_id: int, user: CurrentUser, db: DBSession) -> dict:
    """重新生成报告（用于已提交但报告缺失或需要刷新的考核）。"""
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(404, "考核不存在")
    if exam.user_id != user.id:
        if user.role not in ("teacher", "admin"):
            raise HTTPException(403, "无权操作")
        assert_teacher_can_view_student(db, user, exam.user_id)
    if exam.status != "submitted":
        raise HTTPException(400, "考核尚未提交")
    try:
        report = exam_service.generate_report(db, exam)
    except Exception as e:
        db.rollback()
        exam = db.get(Exam, exam_id)
        report = exam_service.generate_fallback_report(db, exam, str(e))
    return {"exam_id": exam.id, "report_id": report.id, "total_score": report.total_score}


def _assert_student_submitted_exam(exam: Exam | None, user: User) -> Exam:
    if not exam or exam.user_id != user.id:
        raise HTTPException(404, "考核不存在")
    if exam.status != "submitted":
        raise HTTPException(400, "考核尚未提交")
    return exam


class QuestionAskIn(BaseModel):
    question: str


@router.post("/{exam_id}/questions/{idx}/ask")
async def ask_about_question(
    exam_id: int,
    idx: int,
    payload: QuestionAskIn,
    user: CurrentUser,
    db: DBSession,
):
    """考核报告单题追问 SSE：推荐资料 + 流式回答。"""
    exam = _assert_student_submitted_exam(db.get(Exam, exam_id), user)
    if not (payload.question or "").strip():
        raise HTTPException(400, "请输入问题")
    chapter = db.get(Chapter, exam.chapter_id)
    course_id = chapter.course_id if chapter else None
    class_id = get_student_class_for_course(db, user, course_id) if course_id else None
    class_ids = [class_id] if class_id else None

    try:
        llm, stream, recommendations = await exam_feedback_service.prepare_question_ask(
            db, exam, idx, user, payload.question.strip(), class_ids, course_id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    started = time.time()

    async def gen():
        full: list[str] = []
        try:
            yield {
                "event": "recommend",
                "data": json.dumps({"recommendations": recommendations}, ensure_ascii=False),
            }
            async for token in stream:
                full.append(token)
                yield {"event": "message", "data": json.dumps({"text": token}, ensure_ascii=False)}
            yield {"event": "message", "data": "[DONE]"}
            answer = "".join(full)
            exam_feedback_service.save_followup(
                db, exam.id, idx, user.id, payload.question.strip(), answer, recommendations,
            )
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"text": f"LLM 调用失败: {e}"}, ensure_ascii=False)}
        finally:
            latency = int((time.time() - started) * 1000)
            log_call(
                db, endpoint=f"/api/exams/{exam_id}/questions/{idx}/ask", user_id=user.id,
                req_summary=f"[exam:{exam_id} Q{idx}] {payload.question[:80]}",
                resp_summary="".join(full)[:200],
                model_name=llm.model,
                answer_full="".join(full),
                latency_ms=latency,
            )

    return EventSourceResponse(gen())


@router.get("/{exam_id}/questions/{idx}/followups")
def list_question_followups(exam_id: int, idx: int, user: CurrentUser, db: DBSession) -> list:
    exam = _assert_student_submitted_exam(db.get(Exam, exam_id), user)
    return exam_feedback_service.list_followups(db, exam.id, idx, user.id)


@router.post("/{exam_id}/questions/{idx}/grading-feedback")
def submit_grading_feedback(
    exam_id: int,
    idx: int,
    payload: GradingFeedbackIn,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    exam = _assert_student_submitted_exam(db.get(Exam, exam_id), user)
    try:
        return exam_feedback_service.submit_grading_feedback(
            db, exam, idx, user, payload.verdict, payload.comment,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


class InterventionRequestIn(BaseModel):
    message: str = ""


@router.post("/{exam_id}/questions/{idx}/intervention")
def request_intervention(
    exam_id: int,
    idx: int,
    payload: InterventionRequestIn,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    exam = _assert_student_submitted_exam(db.get(Exam, exam_id), user)
    try:
        return exam_feedback_service.request_teacher_intervention(
            db, exam, idx, user, payload.message,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{exam_id}/questions/{idx}/intervention")
def get_intervention(
    exam_id: int,
    idx: int,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    exam = _assert_student_submitted_exam(db.get(Exam, exam_id), user)
    row = exam_feedback_service.get_student_intervention(db, exam, idx, user)
    if not row:
        raise HTTPException(404, "该题暂无教师介入申请")
    return row


@router.get("/{exam_id}/feedback-meta")
def get_feedback_meta(exam_id: int, user: CurrentUser, db: DBSession) -> dict:
    exam = _assert_student_submitted_exam(db.get(Exam, exam_id), user)
    meta = exam_feedback_service.get_report_feedback_meta(db, exam, user.id, viewer=user)
    return meta


@router.get("/{exam_id}/report")
def get_report(exam_id: int, user: CurrentUser, db: DBSession) -> dict:
    exam = _assert_student_submitted_exam(db.get(Exam, exam_id), user)
    report = db.scalar(select(ExamReport).where(ExamReport.exam_id == exam_id))
    if not report:
        raise HTTPException(404, "报告尚未生成")
    return {
        "exam_id": exam_id,
        "chapter_id": exam.chapter_id,
        "dimensions": report.dimensions_json,
        "summary": report.summary,
        "suggestions": report.suggestions,
        "total_score": report.total_score,
        "weak_points": report.weak_points or [],
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "questions": exam_service.exam_to_dict(exam)["questions"],
        "feedback_meta": exam_feedback_service.get_report_feedback_meta(
            db, exam, user.id, viewer=user,
        ),
    }


@router.get("/{exam_id}")
def get_exam(exam_id: int, user: CurrentUser, db: DBSession) -> dict:
    exam = db.get(Exam, exam_id)
    if not exam or exam.user_id != user.id:
        raise HTTPException(404, "考核不存在")
    return exam_service.exam_to_dict(exam)
