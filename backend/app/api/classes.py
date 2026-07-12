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
from ..models import ClassTeacher, TeachingClass, User
from ..schemas.classes import (
    ClassCreateIn,
    ClassMemberOut,
    ClassOut,
    ClassUpdateIn,
    JoinClassIn,
    MyClassOut,
    UsernameIn,
)

router = APIRouter(prefix="/classes", tags=["classes"])


def _gen_invite_code() -> str:
    return secrets.token_hex(3).upper()


def _class_to_out(db: DBSession, cls: TeachingClass) -> ClassOut:
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
    return ClassOut(
        id=cls.id,
        name=cls.name,
        invite_code=cls.invite_code,
        student_count=student_count,
        teacher_count=teacher_count,
        created_at=cls.created_at,
    )


# ---- 学生端 ----

@router.get("/my")
def my_class(user: CurrentUser, db: DBSession) -> MyClassOut:
    if user.role != "student":
        raise HTTPException(403, "仅学生可查看")
    if not user.class_id:
        return MyClassOut()
    cls = db.get(TeachingClass, user.class_id)
    if not cls:
        return MyClassOut()
    teacher_ids = db.scalars(
        select(ClassTeacher.user_id).where(ClassTeacher.class_id == cls.id)
    ).all()
    teachers = []
    for tid in teacher_ids:
        t = db.get(User, tid)
        if t:
            teachers.append(ClassMemberOut(
                id=t.id, username=t.username, display_name=t.display_name
            ))
    return MyClassOut(class_id=cls.id, class_name=cls.name, teachers=teachers)


@router.post("/join")
def join_class(payload: JoinClassIn, user: CurrentUser, db: DBSession) -> dict:
    if user.role != "student":
        raise HTTPException(403, "仅学生可加入班级")
    if user.class_id:
        raise HTTPException(400, "请先退出当前班级")
    code = payload.invite_code.strip().upper()
    cls = db.scalar(select(TeachingClass).where(TeachingClass.invite_code == code))
    if not cls:
        raise HTTPException(404, "邀请码无效")
    user.class_id = cls.id
    db.commit()
    return {"ok": True, "class_id": cls.id, "class_name": cls.name}


@router.post("/leave")
def leave_class(user: CurrentUser, db: DBSession) -> dict:
    if user.role != "student":
        raise HTTPException(403, "仅学生可退出班级")
    if not user.class_id:
        raise HTTPException(400, "当前未加入任何班级")
    user.class_id = None
    db.commit()
    return {"ok": True}


# ---- 教师端 ----

@router.get("/mine", dependencies=[Depends(require_role("teacher"))])
def list_my_classes(user: CurrentUser, db: DBSession) -> list[ClassOut]:
    class_ids = db.scalars(
        select(ClassTeacher.class_id).where(ClassTeacher.user_id == user.id)
    ).all()
    if not class_ids:
        return []
    rows = db.scalars(
        select(TeachingClass).where(TeachingClass.id.in_(class_ids)).order_by(TeachingClass.id)
    ).all()
    return [_class_to_out(db, c) for c in rows]


@router.post("", dependencies=[Depends(require_role("teacher"))])
def create_class(payload: ClassCreateIn, user: CurrentUser, db: DBSession) -> ClassOut:
    cls = TeachingClass(
        name=payload.name.strip(),
        invite_code=_gen_invite_code(),
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


@router.get("/{class_id}/students/available", dependencies=[Depends(require_role("teacher"))])
def list_available_students(class_id: int, user: CurrentUser, db: DBSession) -> list[ClassMemberOut]:
    """可加入该班的学生：未加入任何班级的学生账号。"""
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    rows = db.scalars(
        select(User).where(User.role == "student", User.class_id.is_(None)).order_by(User.id)
    ).all()
    return [
        ClassMemberOut(id=u.id, username=u.username, display_name=u.display_name)
        for u in rows
    ]


@router.get("/{class_id}/students", dependencies=[Depends(require_role("teacher"))])
def list_students(class_id: int, user: CurrentUser, db: DBSession) -> list[ClassMemberOut]:
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    assert_teacher_manages_class(db, user, class_id)
    rows = db.scalars(
        select(User).where(User.role == "student", User.class_id == class_id).order_by(User.id)
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
    target = db.scalar(select(User).where(User.username == payload.username.strip()))
    if not target or target.role != "student":
        raise HTTPException(404, "学生不存在")
    if target.class_id and target.class_id != class_id:
        raise HTTPException(400, "该学生已属于其他班级")
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
    if not target or target.class_id != class_id:
        raise HTTPException(404, "该学生不在本班")
    target.class_id = None
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
    teacher_ids = db.scalars(
        select(ClassTeacher.user_id).where(ClassTeacher.class_id == class_id)
    ).all()
    out = []
    for tid in teacher_ids:
        t = db.get(User, tid)
        if t:
            out.append(ClassMemberOut(id=t.id, username=t.username, display_name=t.display_name))
    return out


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
