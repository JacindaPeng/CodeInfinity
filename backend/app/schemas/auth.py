"""Pydantic schemas —— 用户与认证。"""
from datetime import datetime
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: str = Field(default="student", pattern="^(student|teacher)$")
    display_name: str = ""
    phone: str = Field(min_length=11, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: str = Field(pattern="^(student|teacher|admin)$")
    display_name: str = ""
    phone: str | None = None


class AdminUserUpdate(BaseModel):
    display_name: str | None = None
    role: str | None = Field(default=None, pattern="^(student|teacher|admin)$")
    phone: str | None = None


class AdminResetPasswordIn(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class UserLogin(BaseModel):
    username: str
    password: str


class SmsSendIn(BaseModel):
    phone: str = Field(min_length=11, max_length=20)
    scene: str = Field(pattern="^(register|login)$")


class PhoneLoginIn(BaseModel):
    phone: str = Field(min_length=11, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class EnrollmentOut(BaseModel):
    class_id: int
    class_name: str
    course_id: int
    course_name: str


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    display_name: str
    phone: str | None = None
    class_id: int | None = None
    class_name: str | None = None
    enrollments: list[EnrollmentOut] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


def _mask_phone(phone: str | None) -> str | None:
    if not phone or len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


def build_user_out(user, db: Session) -> UserOut:
    from ..models import ClassEnrollment, ClassTeacher, Course, TeachingClass

    class_name = None
    class_id = user.class_id
    enrollments: list[EnrollmentOut] = []

    if user.role == "student":
        rows = db.scalars(
            select(ClassEnrollment).where(ClassEnrollment.user_id == user.id).order_by(ClassEnrollment.id)
        ).all()
        for row in rows:
            cls = db.get(TeachingClass, row.class_id)
            course = db.get(Course, row.course_id)
            if cls:
                enrollments.append(EnrollmentOut(
                    class_id=cls.id,
                    class_name=cls.name,
                    course_id=row.course_id,
                    course_name=course.name if course else "",
                ))
        if enrollments:
            class_id = enrollments[-1].class_id
            class_name = enrollments[-1].class_name
        elif user.class_id:
            cls = db.get(TeachingClass, user.class_id)
            class_name = cls.name if cls else None
    elif user.role == "teacher":
        class_ids = db.scalars(
            select(ClassTeacher.class_id).where(ClassTeacher.user_id == user.id)
        ).all()
        names: list[str] = []
        for cid in class_ids:
            cls = db.get(TeachingClass, cid)
            if cls:
                names.append(cls.name)
        if names:
            class_name = "、".join(names)

    return UserOut(
        id=user.id,
        username=user.username,
        role=user.role,
        display_name=user.display_name,
        phone=_mask_phone(getattr(user, "phone", None)),
        class_id=class_id,
        class_name=class_name,
        enrollments=enrollments,
        created_at=user.created_at,
    )
