"""班级管理路由：教师创建/管理班级，学生加入/退出。"""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from ..deps import (
    CurrentUser,
    DBSession,
    assert_teacher_manages_class,
    require_role,
)
from ..models import Agent, AgentClass, ClassEnrollment, ClassTeacher, Course, TeachingClass, User
from ..schemas.classes import (
    ClassAgentItem,
    ClassAgentsIn,
    ClassCreateIn,
    ClassMemberOut,
    ClassOut,
    ClassUpdateIn,
    JoinClassIn,
    LeaveClassIn,
    MyEnrollmentOut,
    UsernameIn,
)
from ..services.enrollment import (
    assert_student_not_in_course,
    enroll_student,
    get_class_student_user_ids,
    unenroll_student,
)

router = APIRouter(prefix="/classes", tags=["classes"])


def _gen_invite_code() -> str:
    return secrets.token_hex(3).upper()


def _class_to_out(db: DBSession, cls: TeachingClass) -> ClassOut:
    student_count = db.scalar(
        select(func.count()).select_from(ClassEnrollment).where(
            ClassEnrollment.class_id == cls.id
        )
    ) or 0
    if not student_count:
        student_count = db.scalar(
            select(func.count()).select_from(User).where(
                User.role == "student", User.class_id == cls.id
            )
        ) or 0
    teacher_count = db.scalar(
        select(func.count()).select_from(ClassTeacher).where(
            ClassTeacher.class_id == cls.id
        )
    ) or 0
    course_name = None
    if cls.course_id:
        course = db.get(Course, cls.course_id)
        course_name = course.name if course else None
    return ClassOut(
        id=cls.id,
        name=cls.name,
        invite_code=cls.invite_code,
        course_id=cls.course_id,
        course_name=course_name,
        student_count=student_count,
        teacher_count=teacher_count,
        created_at=cls.created_at,
    )


def _teachers_for_class(db: DBSession, class_id: int) -> list[ClassMemberOut]:
    teacher_ids = db.scalars(
        select(ClassTeacher.user_id).where(ClassTeacher.class_id == class_id)
    ).all()
    out = []
    for tid in teacher_ids:
        t = db.get(User, tid)
        if t:
            out.append(ClassMemberOut(
                id=t.id, username=t.username, display_name=t.display_name
            ))
    return out


def _get_assignable_agents(db: DBSession, user: User, cls: TeachingClass) -> list[Agent]:
    q = select(Agent).where(Agent.owner_id == user.id)
    if cls.course_id:
        q = q.where(Agent.course_id == cls.course_id)
    return list(db.scalars(q.order_by(Agent.id)).all())


# ---- 学生端 ----

@router.get("/my")
def my_classes(user: CurrentUser, db: DBSession) -> list[MyEnrollmentOut]:
    if user.role != "student":
        raise HTTPException(403, "仅学生可查看")
    rows = db.scalars(
        select(ClassEnrollment).where(ClassEnrollment.user_id == user.id).order_by(ClassEnrollment.id)
    ).all()
    if not rows and user.class_id:
        cls = db.get(TeachingClass, user.class_id)
        if cls:
            course = db.get(Course, cls.course_id) if cls.course_id else None
            return [MyEnrollmentOut(
                class_id=cls.id,
                class_name=cls.name,
                course_id=cls.course_id or 0,
                course_name=course.name if course else "",
                teachers=_teachers_for_class(db, cls.id),
            )]
    out = []
    for row in rows:
        cls = db.get(TeachingClass, row.class_id)
        course = db.get(Course, row.course_id)
        if not cls:
            continue
        out.append(MyEnrollmentOut(
            class_id=cls.id,
            class_name=cls.name,
            course_id=row.course_id,
            course_name=course.name if course else "",
            teachers=_teachers_for_class(db, cls.id),
        ))
    return out


@router.post("/join")
def join_class(payload: JoinClassIn, user: CurrentUser, db: DBSession) -> dict:
    if user.role != "student":
        raise HTTPException(403, "仅学生可加入班级")
    code = payload.invite_code.strip().upper()
    cls = db.scalar(select(TeachingClass).where(TeachingClass.invite_code == code))
    if not cls:
        raise HTTPException(404, "邀请码无效")
    enroll_student(db, user, cls)
    db.commit()
    course = db.get(Course, cls.course_id) if cls.course_id else None
    return {
        "ok": True,
        "class_id": cls.id,
        "class_name": cls.name,
        "course_id": cls.course_id,
        "course_name": course.name if course else "",
    }


@router.post("/leave")
def leave_class(
    payload: LeaveClassIn,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    if user.role != "student":
        raise HTTPException(403, "仅学生可退出班级")
    unenroll_student(db, user, payload.class_id)
    db.commit()
    return {"ok": True}


# ---- 教师端 ----

@router.get("/mine", dependencies=[Depends(require_role("teacher"))])
def list_my_classes(user: CurrentUser, db: DBSession) -> list[ClassOut]:
    linked_ids = set(db.scalars(
        select(ClassTeacher.class_id).where(ClassTeacher.user_id == user.id)
    ).all())
    created_ids = set(db.scalars(
        select(TeachingClass.id).where(TeachingClass.created_by == user.id)
    ).all())
    class_ids = sorted(linked_ids | created_ids)
    if not class_ids:
        return []
    rows = db.scalars(
        select(TeachingClass).where(TeachingClass.id.in_(class_ids)).order_by(TeachingClass.id)
    ).all()
    return [_class_to_out(db, c) for c in rows]


@router.post("", dependencies=[Depends(require_role("teacher"))])
def create_class(payload: ClassCreateIn, user: CurrentUser, db: DBSession) -> ClassOut:
    course = db.get(Course, payload.course_id)
    if not course:
        raise HTTPException(404, "课程不存在")
    cls = TeachingClass(
        name=payload.name.strip(),
        invite_code=_gen_invite_code(),
        course_id=payload.course_id,
        created_by=user.id,
    )
    db.add(cls)
    db.flush()
    db.add(ClassTeacher(class_id=cls.id, user_id=user.id))
    db.commit()
    db.refresh(cls)
    return _class_to_out(db, cls)


@router.put("/{class_id}", dependencies=[Depends(require_role("teacher"))])
def update_class(
    class_id: int, payload: ClassUpdateIn, user: CurrentUser, db: DBSession
) -> ClassOut:
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    cls.name = payload.name.strip()
    db.commit()
    db.refresh(cls)
    return _class_to_out(db, cls)


@router.delete("/{class_id}", dependencies=[Depends(require_role("teacher"))])
def delete_class(class_id: int, user: CurrentUser, db: DBSession) -> dict:
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    for row in db.scalars(
        select(AgentClass).where(AgentClass.class_id == class_id)
    ).all():
        db.delete(row)
    for row in db.scalars(
        select(ClassEnrollment).where(ClassEnrollment.class_id == class_id)
    ).all():
        u = db.get(User, row.user_id)
        if u and u.class_id == class_id:
            u.class_id = None
        db.delete(row)
    for s in db.scalars(select(User).where(User.class_id == class_id)).all():
        s.class_id = None
    db.delete(cls)
    db.commit()
    return {"ok": True}


@router.post("/{class_id}/regenerate-code", dependencies=[Depends(require_role("teacher"))])
def regenerate_code(class_id: int, user: CurrentUser, db: DBSession) -> dict:
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    cls.invite_code = _gen_invite_code()
    db.commit()
    return {"invite_code": cls.invite_code}


@router.get("/{class_id}/agents", dependencies=[Depends(require_role("teacher"))])
def list_class_agents(class_id: int, user: CurrentUser, db: DBSession) -> list[ClassAgentItem]:
    """班级可用智能体：本人可勾选；其他教师已分配的仅展示。"""
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    if not cls.course_id:
        raise HTTPException(400, "请先为班级绑定课程后再分配智能体")

    assigned_rows = db.scalars(
        select(AgentClass).where(AgentClass.class_id == class_id)
    ).all()
    assigned_agent_ids = {r.agent_id for r in assigned_rows}
    mine_ids = {a.id for a in _get_assignable_agents(db, user, cls)}
    out: list[ClassAgentItem] = []
    seen: set[int] = set()

    for a in _get_assignable_agents(db, user, cls):
        course_name = ""
        if a.course_id:
            c = db.get(Course, a.course_id)
            course_name = c.name if c else ""
        out.append(ClassAgentItem(
            id=a.id,
            name=a.name,
            course_name=course_name,
            status=a.status or "active",
            is_adopted=bool(a.source_agent_id),
            assigned=a.id in assigned_agent_ids,
            owner_name=user.display_name or user.username,
            is_mine=True,
            editable=True,
        ))
        seen.add(a.id)

    for aid in assigned_agent_ids:
        if aid in seen:
            continue
        a = db.get(Agent, aid)
        if not a:
            continue
        owner = db.get(User, a.owner_id) if a.owner_id else None
        course_name = ""
        if a.course_id:
            c = db.get(Course, a.course_id)
            course_name = c.name if c else ""
        out.append(ClassAgentItem(
            id=a.id,
            name=a.name,
            course_name=course_name,
            status=a.status or "active",
            is_adopted=bool(a.source_agent_id),
            assigned=True,
            owner_name=(owner.display_name or owner.username) if owner else "",
            is_mine=False,
            editable=False,
        ))
    return out


@router.put("/{class_id}/agents", dependencies=[Depends(require_role("teacher"))])
def set_class_agents(
    class_id: int, payload: ClassAgentsIn, user: CurrentUser, db: DBSession
) -> dict:
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    if not cls.course_id:
        raise HTTPException(400, "请先为班级绑定课程后再分配智能体")

    assignable = {a.id: a for a in _get_assignable_agents(db, user, cls)}
    unique_ids = list(dict.fromkeys(payload.agent_ids))
    for aid in unique_ids:
        if aid not in assignable:
            raise HTTPException(403, f"无权为班级分配智能体 {aid}")

    my_agent_ids = set(assignable.keys())
    if my_agent_ids:
        for row in db.scalars(
            select(AgentClass).where(
                AgentClass.class_id == class_id,
                AgentClass.agent_id.in_(my_agent_ids),
            )
        ).all():
            db.delete(row)
        db.flush()
    for aid in unique_ids:
        db.add(AgentClass(agent_id=aid, class_id=class_id, assigned_by=user.id))
    db.commit()
    return {"ok": True, "agent_ids": unique_ids}


@router.get("/{class_id}/students/available", dependencies=[Depends(require_role("teacher"))])
def list_available_students(class_id: int, user: CurrentUser, db: DBSession) -> list[ClassMemberOut]:
    """可加入该班的学生：尚未在本课程其他班级中的学生。"""
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    if not cls.course_id:
        raise HTTPException(400, "班级尚未绑定课程")

    in_course = set(db.scalars(
        select(ClassEnrollment.user_id).where(ClassEnrollment.course_id == cls.course_id)
    ).all())
    in_class = set(db.scalars(
        select(ClassEnrollment.user_id).where(ClassEnrollment.class_id == class_id)
    ).all())
    rows = db.scalars(
        select(User).where(User.role == "student").order_by(User.id)
    ).all()
    return [
        ClassMemberOut(id=u.id, username=u.username, display_name=u.display_name)
        for u in rows
        if u.id not in in_course or u.id in in_class
    ]


@router.get("/{class_id}/students", dependencies=[Depends(require_role("teacher"))])
def list_students(class_id: int, user: CurrentUser, db: DBSession) -> list[ClassMemberOut]:
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    student_ids = get_class_student_user_ids(db, [class_id])
    if not student_ids:
        return []
    rows = db.scalars(
        select(User).where(User.id.in_(student_ids)).order_by(User.id)
    ).all()
    return [
        ClassMemberOut(id=u.id, username=u.username, display_name=u.display_name)
        for u in rows
    ]


@router.post("/{class_id}/students", dependencies=[Depends(require_role("teacher"))])
def add_student(
    class_id: int, payload: UsernameIn, user: CurrentUser, db: DBSession
) -> dict:
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    if not cls.course_id:
        raise HTTPException(400, "班级尚未绑定课程")
    target = db.scalar(select(User).where(User.username == payload.username.strip()))
    if not target or target.role != "student":
        raise HTTPException(404, "学生不存在")
    existing = db.scalar(
        select(ClassEnrollment).where(
            ClassEnrollment.user_id == target.id,
            ClassEnrollment.class_id == class_id,
        )
    )
    if existing:
        return {"ok": True}
    assert_student_not_in_course(db, target.id, cls.course_id)
    db.add(ClassEnrollment(
        user_id=target.id, class_id=class_id, course_id=cls.course_id
    ))
    target.class_id = class_id
    db.commit()
    return {"ok": True}


@router.delete("/{class_id}/students/{student_id}", dependencies=[Depends(require_role("teacher"))])
def remove_student(
    class_id: int, student_id: int, user: CurrentUser, db: DBSession
) -> dict:
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    target = db.get(User, student_id)
    row = db.scalar(
        select(ClassEnrollment).where(
            ClassEnrollment.user_id == student_id,
            ClassEnrollment.class_id == class_id,
        )
    )
    if not target or not row:
        raise HTTPException(404, "该学生不在本班")
    db.delete(row)
    if target.class_id == class_id:
        remaining = db.scalar(
            select(ClassEnrollment.class_id)
            .where(ClassEnrollment.user_id == student_id)
            .order_by(ClassEnrollment.id)
            .limit(1)
        )
        target.class_id = remaining
    db.commit()
    return {"ok": True}


@router.get("/{class_id}/teachers/available", dependencies=[Depends(require_role("teacher"))])
def list_available_assistants(class_id: int, user: CurrentUser, db: DBSession) -> list[ClassMemberOut]:
    """可加入该班的助教：尚未管理该班级的教师/管理员账号。"""
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    existing_ids = set(db.scalars(
        select(ClassTeacher.user_id).where(ClassTeacher.class_id == class_id)
    ).all())
    rows = db.scalars(
        select(User).where(User.role.in_(("teacher", "admin"))).order_by(User.id)
    ).all()
    return [
        ClassMemberOut(id=u.id, username=u.username, display_name=u.display_name)
        for u in rows if u.id not in existing_ids
    ]


@router.get("/{class_id}/teachers", dependencies=[Depends(require_role("teacher"))])
def list_teachers(class_id: int, user: CurrentUser, db: DBSession) -> list[ClassMemberOut]:
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    return _teachers_for_class(db, class_id)


@router.post("/{class_id}/teachers", dependencies=[Depends(require_role("teacher"))])
def add_teacher(
    class_id: int, payload: UsernameIn, user: CurrentUser, db: DBSession
) -> dict:
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    target = db.scalar(select(User).where(User.username == payload.username.strip()))
    if not target or target.role not in ("teacher", "admin"):
        raise HTTPException(404, "助教不存在")
    exists = db.scalar(
        select(ClassTeacher).where(
            ClassTeacher.class_id == class_id, ClassTeacher.user_id == target.id
        )
    )
    if exists:
        raise HTTPException(400, "该助教已在班级中")
    db.add(ClassTeacher(class_id=class_id, user_id=target.id))
    db.commit()
    return {"ok": True}


@router.delete("/{class_id}/teachers/{teacher_id}", dependencies=[Depends(require_role("teacher"))])
def remove_teacher(
    class_id: int, teacher_id: int, user: CurrentUser, db: DBSession
) -> dict:
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    count = db.scalar(
        select(func.count()).select_from(ClassTeacher).where(ClassTeacher.class_id == class_id)
    ) or 0
    if count <= 1:
        raise HTTPException(400, "班级至少保留一名管理教师")
    link = db.scalar(
        select(ClassTeacher).where(
            ClassTeacher.class_id == class_id, ClassTeacher.user_id == teacher_id
        )
    )
    if not link:
        raise HTTPException(404, "该助教不在本班")
    db.delete(link)
    db.commit()
    return {"ok": True}
