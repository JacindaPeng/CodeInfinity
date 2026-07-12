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


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: str = Field(pattern="^(student|teacher|admin)$")
    display_name: str = ""


class AdminUserUpdate(BaseModel):
    display_name: str | None = None
    role: str | None = Field(default=None, pattern="^(student|teacher|admin)$")


class AdminResetPasswordIn(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class UserLogin(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    display_name: str
    class_id: int | None = None
    class_name: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


def build_user_out(user, db: Session) -> UserOut:
    from ..models import ClassTeacher, TeachingClass

    class_name = None
    if user.role == "student" and user.class_id:
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
        class_id=user.class_id,
        class_name=class_name,
        created_at=user.created_at,
    )
