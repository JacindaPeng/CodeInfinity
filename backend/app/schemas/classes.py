"""班级相关 Pydantic schemas。"""
from datetime import datetime

from pydantic import BaseModel, Field


class ClassCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    course_id: int


class ClassUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class ClassOut(BaseModel):
    id: int
    name: str
    invite_code: str
    course_id: int | None = None
    course_name: str | None = None
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


class LeaveClassIn(BaseModel):
    class_id: int


class UsernameIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class MyEnrollmentOut(BaseModel):
    class_id: int
    class_name: str
    course_id: int
    course_name: str
    teachers: list[ClassMemberOut] = []


class ClassAgentsIn(BaseModel):
    agent_ids: list[int] = Field(default_factory=list)


class ClassAgentItem(BaseModel):
    id: int
    name: str
    course_name: str
    status: str
    is_adopted: bool
    assigned: bool
    owner_name: str = ""
    is_mine: bool = False
    editable: bool = True
