"""学生多班级选课：每门课程最多加入一个班级。"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ClassEnrollment, Course, TeachingClass, User


def get_student_enrollments(db: Session, user: User) -> list[ClassEnrollment]:
    if user.role != "student":
        return []
    return list(db.scalars(
        select(ClassEnrollment).where(ClassEnrollment.user_id == user.id).order_by(ClassEnrollment.id)
    ).all())


def get_student_class_ids(db: Session, user: User) -> list[int]:
    return [e.class_id for e in get_student_enrollments(db, user)]


def get_student_class_for_course(db: Session, user: User, course_id: int | None) -> int | None:
    if user.role != "student" or not course_id:
        return None
    row = db.scalar(
        select(ClassEnrollment).where(
            ClassEnrollment.user_id == user.id,
            ClassEnrollment.course_id == course_id,
        )
    )
    return row.class_id if row else None


def assert_student_enrolled(db: Session, user: User, class_id: int) -> ClassEnrollment:
    row = db.scalar(
        select(ClassEnrollment).where(
            ClassEnrollment.user_id == user.id,
            ClassEnrollment.class_id == class_id,
        )
    )
    if not row:
        raise HTTPException(403, "您未加入该班级")
    return row


def assert_student_not_in_course(db: Session, user_id: int, course_id: int, exclude_class_id: int | None = None) -> None:
    q = select(ClassEnrollment).where(
        ClassEnrollment.user_id == user_id,
        ClassEnrollment.course_id == course_id,
    )
    if exclude_class_id:
        q = q.where(ClassEnrollment.class_id != exclude_class_id)
    existing = db.scalar(q)
    if existing:
        course = db.get(Course, course_id)
        other = db.get(TeachingClass, existing.class_id)
        cname = course.name if course else f"课程{course_id}"
        oname = other.name if other else f"班级{existing.class_id}"
        raise HTTPException(400, f"该学生已在「{cname}」加入了班级「{oname}」，每门课程只能加入一个班级")


def enroll_student(db: Session, user: User, cls: TeachingClass) -> ClassEnrollment:
    if user.role != "student":
        raise HTTPException(403, "仅学生可加入班级")
    if not cls.course_id:
        raise HTTPException(400, "该班级尚未绑定课程，请联系教师")
    assert_student_not_in_course(db, user.id, cls.course_id)
    row = ClassEnrollment(user_id=user.id, class_id=cls.id, course_id=cls.course_id)
    db.add(row)
    user.class_id = cls.id
    return row


def unenroll_student(db: Session, user: User, class_id: int) -> None:
    row = db.scalar(
        select(ClassEnrollment).where(
            ClassEnrollment.user_id == user.id,
            ClassEnrollment.class_id == class_id,
        )
    )
    if not row:
        raise HTTPException(400, "您未加入该班级")
    db.delete(row)
    if user.class_id == class_id:
        remaining = db.scalar(
            select(ClassEnrollment.class_id)
            .where(ClassEnrollment.user_id == user.id)
            .order_by(ClassEnrollment.id)
            .limit(1)
        )
        user.class_id = remaining


def get_class_student_user_ids(db: Session, class_ids: list[int]) -> list[int]:
    if not class_ids:
        return []
    rows = db.scalars(
        select(ClassEnrollment.user_id).where(ClassEnrollment.class_id.in_(class_ids))
    ).all()
    if rows:
        return list(rows)
    return list(db.scalars(
        select(User.id).where(User.role == "student", User.class_id.in_(class_ids))
    ).all())
