"""课程列表与创建 API。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from ..deps import CurrentUser, DBSession, require_role
from ..models import Course

router = APIRouter(prefix="/courses", tags=["courses"])


class CourseIn(BaseModel):
    name: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("课程名称不能为空")
        return v


@router.get("")
def list_courses(_u: CurrentUser, db: DBSession) -> list[dict]:
    rows = db.scalars(select(Course).order_by(Course.id)).all()
    return [
        {"id": c.id, "name": c.name, "description": c.description or ""}
        for c in rows
    ]


@router.post("", status_code=201, dependencies=[Depends(require_role("teacher", "admin"))])
def create_course(payload: CourseIn, db: DBSession) -> dict:
    existing = db.scalar(select(Course).where(Course.name == payload.name))
    if existing:
        return {
            "id": existing.id,
            "name": existing.name,
            "description": existing.description or "",
        }
    course = Course(name=payload.name, description=(payload.description or "").strip())
    db.add(course)
    db.commit()
    db.refresh(course)
    return {
        "id": course.id,
        "name": course.name,
        "description": course.description or "",
    }