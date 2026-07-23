"""系统管理员 API：用户管理、全站监控。"""
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, func, select

from ..deps import CurrentUser, DBSession, require_role
from ..models import (
    Agent,
    AgentClass,
    CallLog,
    Chapter,
    ClassEnrollment,
    ClassTeacher,
    Course,
    Exam,
    ExamReport,
    TeachingClass,
    User,
)
from ..services.enrollment import get_class_student_user_ids
from ..schemas import AdminResetPasswordIn, AdminUserCreate, AdminUserUpdate, UserOut, build_user_out
from ..schemas.classes import ClassOut
from ..security import hash_password
from ..services import exam_service, exam_feedback_service
from .agents import _agent_dict
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
    db.execute(delete(ClassEnrollment).where(ClassEnrollment.user_id == user_id))
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
        student_ids = get_class_student_user_ids(db, [class_id])
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
        student_ids = get_class_student_user_ids(db, [class_id])
        if not student_ids:
            return []
        base = base.where(User.id.in_(student_ids))
    rows = db.scalars(base.order_by(User.id)).all()
    return [{"id": u.id, "username": u.username, "display_name": u.display_name} for u in rows]


@router.get("/exams/{exam_id}/report")
def admin_get_report(exam_id: int, user: CurrentUser, db: DBSession) -> dict:
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
        "feedback_meta": exam_feedback_service.get_report_feedback_meta(
            db, exam, exam.user_id, viewer=user,
        ),
        "student_feedback_credit": (u.feedback_credit or 0) if u else 0,
    }


# ---- AI 判卷反馈与训练监控 ----

@router.get("/ai-feedback/overview")
def admin_ai_feedback_overview(db: DBSession) -> dict:
    return exam_feedback_service.get_admin_feedback_overview(db)


@router.get("/ai-feedback/records")
def admin_ai_feedback_records(
    db: DBSession,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> dict:
    return exam_feedback_service.list_admin_feedback_records(db, page=page, size=size)


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
        student_ids = get_class_student_user_ids(db, [class_id])
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


# ---- 智能体管理 ----

class AdminAgentIn(BaseModel):
    name: str
    intro: str = ""
    endpoint: str = "/api/agents/course/ask"
    course_id: int | None = None
    slug: str
    status: str = "planned"
    owner_id: int | None = None
    is_shared: bool = False

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("名称不能为空")
        return v

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("请选择编程语言（slug 不能为空）")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", v):
            raise ValueError("slug 仅允许小写字母、数字与连字符")
        return v

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str) -> str:
        if v not in ("active", "planned"):
            raise ValueError("status 须为 active 或 planned")
        return v


def _assert_agent_course(db: DBSession, course_id: int | None) -> None:
    if course_id is not None and not db.get(Course, course_id):
        raise HTTPException(404, "绑定课程不存在")


def _assert_slug_unique(db: DBSession, slug: str, owner_id: int | None, exclude_id: int | None = None) -> None:
    if not slug:
        return
    q = select(Agent).where(Agent.slug == slug)
    if owner_id is not None:
        q = q.where(Agent.owner_id == owner_id)
    if exclude_id:
        q = q.where(Agent.id != exclude_id)
    if db.scalar(q):
        raise HTTPException(400, f"slug「{slug}」已存在")


@router.get("/agents")
def list_agents_admin(db: DBSession) -> list[dict]:
    rows = db.scalars(select(Agent).order_by(Agent.id)).all()
    return [_agent_dict(a, db) for a in rows]


@router.post("/agents", status_code=201)
def create_agent_admin(payload: AdminAgentIn, db: DBSession) -> dict:
    _assert_agent_course(db, payload.course_id)
    _assert_slug_unique(db, payload.slug, payload.owner_id)
    agent = Agent(
        name=payload.name,
        intro=payload.intro,
        endpoint=payload.endpoint or "/api/agents/course/ask",
        course_id=payload.course_id,
        slug=payload.slug,
        status=payload.status,
        owner_id=payload.owner_id,
        is_shared=payload.is_shared,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return _agent_dict(agent, db)


@router.put("/agents/{agent_id}")
def update_agent_admin(agent_id: int, payload: AdminAgentIn, db: DBSession) -> dict:
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    _assert_agent_course(db, payload.course_id)
    _assert_slug_unique(db, payload.slug, payload.owner_id if payload.owner_id is not None else agent.owner_id, exclude_id=agent_id)
    agent.name = payload.name
    agent.intro = payload.intro
    agent.endpoint = payload.endpoint or "/api/agents/course/ask"
    agent.course_id = payload.course_id
    agent.slug = payload.slug
    agent.status = payload.status
    if payload.owner_id is not None:
        agent.owner_id = payload.owner_id
    agent.is_shared = payload.is_shared
    db.commit()
    db.refresh(agent)
    return _agent_dict(agent, db)


@router.delete("/agents/{agent_id}")
def delete_agent_admin(agent_id: int, db: DBSession) -> dict:
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    db.delete(agent)
    db.commit()
    return {"ok": True}
