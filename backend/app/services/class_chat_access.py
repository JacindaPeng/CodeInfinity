"""课程群聊权限：本班学生 / 本班教师 / admin。"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import assert_teacher_manages_class, get_managed_class_ids
from ..models import ClassTeacher, TeachingClass, User
from .enrollment import assert_student_enrolled, get_class_student_user_ids, get_student_class_ids


def assert_class_chat_member(db: Session, user: User, class_id: int) -> TeachingClass:
    """学生须选课；教师须管理该班；admin 放行。"""
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    if user.role == "admin":
        return cls
    if user.role == "teacher":
        assert_teacher_manages_class(db, user, class_id)
        return cls
    if user.role == "student":
        # 兼容仅有 legacy class_id、尚未写入 enrollments 的旧账号
        try:
            assert_student_enrolled(db, user, class_id)
        except HTTPException:
            if user.class_id == class_id:
                return cls
            raise
        return cls
    raise HTTPException(403, "无权访问该班级群聊")


def list_class_teacher_users(db: Session, class_id: int) -> list[User]:
    """本班任课教师（class_teachers ∪ created_by）。"""
    cls = db.get(TeachingClass, class_id)
    if not cls:
        return []
    ids = set(db.scalars(
        select(ClassTeacher.user_id).where(ClassTeacher.class_id == class_id)
    ).all())
    ids.add(cls.created_by)
    if not ids:
        return []
    return list(db.scalars(
        select(User).where(User.id.in_(ids)).order_by(User.id)
    ).all())


def list_class_student_users(db: Session, class_id: int) -> list[User]:
    student_ids = get_class_student_user_ids(db, [class_id])
    if not student_ids:
        return []
    return list(db.scalars(
        select(User).where(User.id.in_(student_ids)).order_by(User.id)
    ).all())


def assert_dm_peer_allowed(
    db: Session,
    user: User,
    class_id: int,
    peer_id: int,
) -> User:
    """校验私信对方合法：学生只能找本班教师；教师只能找本班学生。双方都必须是本班成员。"""
    if peer_id == user.id:
        raise HTTPException(400, "不能给自己发私信")
    peer = db.get(User, peer_id)
    if not peer:
        raise HTTPException(404, "对方用户不存在")

    teacher_ids = {u.id for u in list_class_teacher_users(db, class_id)}
    student_ids = set(get_class_student_user_ids(db, [class_id]))

    if user.role == "admin":
        return peer

    if user.role == "student":
        if user.id not in student_ids and user.class_id != class_id:
            raise HTTPException(403, "您未加入该班级")
        if peer.id not in teacher_ids:
            raise HTTPException(403, "只能向本班教师私信")
        return peer

    if user.role == "teacher":
        managed = get_managed_class_ids(db, user) or []
        if class_id not in managed:
            raise HTTPException(403, "无权管理该班级")
        if peer.id not in student_ids:
            raise HTTPException(403, "只能向本班学生私信")
        return peer

    raise HTTPException(403, "无权发送私信")


def is_user_in_class(db: Session, user: User, class_id: int) -> bool:
    if user.role == "admin":
        return True
    if user.role == "teacher":
        managed = get_managed_class_ids(db, user)
        return managed is None or class_id in (managed or [])
    if user.role == "student":
        return class_id in get_student_class_ids(db, user) or user.class_id == class_id
    return False
