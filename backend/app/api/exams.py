"""考核路由：学生端开始/答题/交卷/报告 + 教师端配置/题库/知识点/学生记录。

路由顺序：具体路径（/start, /history/*, /teacher/*, /config/*, /bank/*, /knowledge-points/*）
必须定义在 /{exam_id} 通配之前，避免被 {exam_id} 抢占匹配。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from ..deps import CurrentUser, DBSession, require_role, resolve_teacher_scope, assert_teacher_can_view_student, assert_can_access_question, assert_teacher_upload_class, resolve_resource_class_ids, resolve_config_class_id, get_exam_config
from ..models import (
    Chapter,
    Exam,
    ExamConfig,
    ExamQuestion,
    ExamReport,
    KnowledgePoint,
    QuestionBank,
    TeachingClass,
    User,
)
from ..services import exam_service

router = APIRouter(prefix="/exams", tags=["exams"])


# ============ 具体路径（优先匹配） ============

class StartIn(BaseModel):
    chapter_id: int
    class_id: int | None = None  # 教师考核测试时指定班级


@router.post("/start")
def start_exam(payload: StartIn, user: CurrentUser, db: DBSession) -> dict:
    try:
        if user.role == "student":
            exam_class_id = user.class_id
            teacher_test = False
        else:
            if not payload.class_id:
                raise HTTPException(400, "请指定班级")
            exam_class_id = resolve_config_class_id(db, user, payload.class_id)
            teacher_test = True
        exam, warnings = exam_service.generate_paper(
            db, user, payload.chapter_id,
            class_id=exam_class_id,
            teacher_test=teacher_test,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "exam_id": exam.id,
        "questions": exam_service.exam_to_dict(exam)["questions"],
        "warnings": warnings,
    }


@router.get("/history/mine")
def my_history(user: CurrentUser, db: DBSession) -> list[dict]:
    rows = db.scalars(select(Exam).where(Exam.user_id == user.id).order_by(Exam.id.desc())).all()
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
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> dict:
    """教师查看所管班级学生的考核记录（含分数）。"""
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
    assert_teacher_can_view_student(db, user, exam.user_id)
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
    }


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
) -> dict:
    cid = resolve_config_class_id(db, user, class_id)
    cfg = get_exam_config(db, chapter_id, cid)
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
) -> dict:
    """返回当前用户在指定章节的考核次数、上限、剩余次数。"""
    if user.role == "student":
        cid = resolve_config_class_id(db, user)
    else:
        cid = resolve_config_class_id(db, user, class_id)
    cfg = get_exam_config(db, chapter_id, cid)
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
) -> dict:
    """教师查看所管班级各章节考核完成率。"""
    resolve_config_class_id(db, user, class_id)
    _, student_ids = resolve_teacher_scope(db, user, class_id)
    student_count = len(student_ids)
    chapters = db.scalars(select(Chapter).order_by(Chapter.order_idx, Chapter.id)).all()
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
) -> list[dict]:
    allowed_classes = resolve_resource_class_ids(db, user, class_id)
    q = select(QuestionBank).order_by(QuestionBank.id.desc())
    if chapter_id:
        q = q.where(QuestionBank.chapter_id == chapter_id)
    if allowed_classes is not None:
        if not allowed_classes:
            return []
        q = q.where(QuestionBank.class_id.in_(allowed_classes))
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


@router.get("/knowledge-points/{chapter_id}")
def list_kps(
    chapter_id: int,
    user: CurrentUser,
    db: DBSession,
    class_id: int | None = Query(default=None),
) -> list[dict]:
    cid = resolve_config_class_id(db, user, class_id)
    rows = db.scalars(
        select(KnowledgePoint).where(
            KnowledgePoint.chapter_id == chapter_id,
            KnowledgePoint.class_id == cid,
        )
    ).all()
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


@router.get("/{exam_id}/report")
def get_report(exam_id: int, user: CurrentUser, db: DBSession) -> dict:
    exam = db.get(Exam, exam_id)
    if not exam or exam.user_id != user.id:
        raise HTTPException(404, "考核不存在")
    if exam.status != "submitted":
        raise HTTPException(400, "尚未提交")
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
    }


@router.get("/{exam_id}")
def get_exam(exam_id: int, user: CurrentUser, db: DBSession) -> dict:
    exam = db.get(Exam, exam_id)
    if not exam or exam.user_id != user.id:
        raise HTTPException(404, "考核不存在")
    return exam_service.exam_to_dict(exam)
