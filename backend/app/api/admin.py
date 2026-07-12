"""系统管理员 API：用户管理、全站监控。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select

from ..deps import CurrentUser, DBSession, require_role
from ..models import (
    CallLog,
    Chapter,
    ClassTeacher,
    Exam,
    ExamReport,
    TeachingClass,
    User,
)
from ..schemas import AdminResetPasswordIn, AdminUserCreate, AdminUserUpdate, UserOut, build_user_out
from ..schemas.classes import ClassOut
from ..security import hash_password
from ..services import exam_service
from .classes import _class_to_out

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role("admin"))])


def _count_admins(db: DBSession) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0


def _assert_not_last_admin(db: DBSession, user: User, new_role: str | None = None) -> None:
    if user.role != "admin":
        return
    if new_role and new_role != "admin":
        if _count_admins(db) <= 1:
            raise HTTPException(400, "系统至少保留一名管理员")
    elif _count_admins(db) <= 1:
        raise HTTPException(400, "不能删除或降级最后一名管理员")


# ---- 用户管理 ----

@router.get("/users")
def list_users(
    db: DBSession,
    role: str | None = Query(default=None),
    username: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> dict:
    base = select(User)
    if role:
        base = base.where(User.role == role)
    if username:
        base = base.where(User.username.contains(username.strip()))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(User.id).offset((page - 1) * size).limit(size)
    ).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [build_user_out(u, db) for u in rows],
    }


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: AdminUserCreate, db: DBSession) -> UserOut:
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(400, "用户名已存在")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        display_name=payload.display_name or payload.username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return build_user_out(user, db)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    admin: CurrentUser,
    db: DBSession,
) -> UserOut:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    if payload.role and payload.role != user.role:
        if user_id == admin.id:
            raise HTTPException(400, "不能修改自己的角色")
        _assert_not_last_admin(db, user, payload.role)
        user.role = payload.role
    if payload.display_name is not None:
        user.display_name = payload.display_name
    db.commit()
    db.refresh(user)
    return build_user_out(user, db)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: CurrentUser, db: DBSession) -> dict:
    if user_id == admin.id:
        raise HTTPException(400, "不能删除当前登录账号")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    _assert_not_last_admin(db, user)
    user.class_id = None
    db.execute(delete(ClassTeacher).where(ClassTeacher.user_id == user_id))
    db.delete(user)
    db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, payload: AdminResetPasswordIn, db: DBSession) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    user.password_hash = hash_password(payload.password)
    db.commit()
    return {"ok": True}


# ---- 全站班级 ----

@router.get("/classes", response_model=list[ClassOut])
def list_all_classes(db: DBSession) -> list[ClassOut]:
    rows = db.scalars(select(TeachingClass).order_by(TeachingClass.id)).all()
    return [_class_to_out(db, c) for c in rows]


# ---- 全站考核监控 ----

@router.get("/exams")
def admin_list_exams(
    db: DBSession,
    chapter_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    class_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> dict:
    base = select(Exam)
    if class_id:
        student_ids = db.scalars(
            select(User.id).where(User.role == "student", User.class_id == class_id)
        ).all()
        if not student_ids:
            return {"total": 0, "page": page, "size": size, "items": []}
        base = base.where(Exam.user_id.in_(student_ids))
    if chapter_id:
        base = base.where(Exam.chapter_id == chapter_id)
    if user_id:
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


@router.get("/exams/students")
def admin_list_students(
    db: DBSession,
    class_id: int | None = Query(default=None),
) -> list[dict]:
    base = select(User).where(User.role == "student")
    if class_id:
        base = base.where(User.class_id == class_id)
    rows = db.scalars(base.order_by(User.id)).all()
    return [{"id": u.id, "username": u.username, "display_name": u.display_name} for u in rows]


@router.get("/exams/{exam_id}/report")
def admin_get_report(exam_id: int, db: DBSession) -> dict:
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(404, "考核不存在")
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


# ---- 全站调用日志 ----

@router.get("/logs")
def admin_list_logs(
    db: DBSession,
    endpoint: str | None = Query(default=None),
    class_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> dict:
    base = select(CallLog)
    if class_id:
        student_ids = db.scalars(
            select(User.id).where(User.role == "student", User.class_id == class_id)
        ).all()
        if not student_ids:
            return {"total": 0, "page": page, "size": size, "items": []}
        base = base.where(CallLog.user_id.in_(student_ids))
    if endpoint:
        base = base.where(CallLog.endpoint == endpoint)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(CallLog.id.desc()).offset((page - 1) * size).limit(size)
    ).all()

    user_map: dict[int, User] = {}
    user_ids = {r.user_id for r in rows if r.user_id}
    if user_ids:
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all():
            user_map[u.id] = u

    return {
        "total": total, "page": page, "size": size,
        "items": [
            {
                "id": r.id, "user_id": r.user_id,
                "username": user_map[r.user_id].username if r.user_id and r.user_id in user_map else "",
                "display_name": user_map[r.user_id].display_name if r.user_id and r.user_id in user_map else "",
                "endpoint": r.endpoint,
                "req_summary": r.req_summary, "resp_summary": r.resp_summary,
                "model_name": r.model_name or "", "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
