"""课程智能体辅助：上传教材后自动启用筹备中智能体。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Agent, Chapter, Material


def maybe_activate_course_agent(db: Session, course_id: int) -> bool:
    """若课程已有资料且智能体为筹备中，则自动设为已上线。"""
    agent = db.scalar(select(Agent).where(Agent.course_id == course_id))
    if not agent or agent.status == "active":
        return False
    chapter_ids = db.scalars(
        select(Chapter.id).where(Chapter.course_id == course_id)
    ).all()
    if not chapter_ids:
        return False
    has_material = db.scalar(
        select(Material.id).where(Material.chapter_id.in_(chapter_ids)).limit(1)
    )
    if not has_material:
        return False
    agent.status = "active"
    db.commit()
    return True
