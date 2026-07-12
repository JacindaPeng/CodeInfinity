"""班级相关 Pydantic schemas。"""
from datetime import datetime

from pydantic import BaseModel, Field


class ClassCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class ClassUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class ClassOut(BaseModel):
    id: int
    name: str
    invite_code: str
    student_count: int = 0
    teacher_count: int = 0
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ClassMemberOut(BaseModel):
    id: int
    username: str
    display_name: str


class JoinClassIn(BaseModel):
    invite_code: str = Field(min_length=4, max_length=8)


class UsernameIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class MyClassOut(BaseModel):
    class_id: int | None = None
    class_name: str | None = None
    teachers: list[ClassMemberOut] = []
