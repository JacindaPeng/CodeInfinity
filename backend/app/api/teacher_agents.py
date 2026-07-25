"""教师课程智能体：创建、共享、采纳、班级绑定。"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, func, select

from ..deps import CurrentUser, DBSession, get_managed_class_ids, require_role
from ..models import Agent, AgentClass, Course, ExamConfig, KnowledgePoint, Material, QuestionBank, TeachingClass, User
from ..services.agent_access import assert_agent_owner, get_bound_class_ids, get_shared_content_class_ids
from ..services.agent_adopt import (
    clone_agent_content_snapshot,
    schedule_index_adopted_materials,
    propagate_snapshot_to_classes,
    repair_adopted_chapter_links,
)
from .agents import _agent_dict

router = APIRouter(prefix="/teacher/agents", tags=["teacher-agents"])


class TeacherAgentIn(BaseModel):
    name: str
    intro: str = ""
    course_id: int | None = None
    slug: str
    status: str = "planned"

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("名称不能为空")
        return v

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("请选择编程语言（slug 不能为空）")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", v):
            raise ValueError("slug 仅允许小写字母、数字与连字符")
        return v

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str) -> str:
        if v not in ("active", "planned"):
            raise ValueError("status 须为 active 或 planned")
        return v


class AgentClassesIn(BaseModel):
    class_ids: list[int]


class ShareAgentIn(BaseModel):
    is_shared: bool


def _find_adopted(db: DBSession, user_id: int, source_id: int) -> Agent | None:
    return db.scalar(
        select(Agent)
        .where(Agent.owner_id == user_id, Agent.source_agent_id == source_id)
        .order_by(Agent.id)
    )


def _dedupe_adopted_copies(db: DBSession, user_id: int, source_id: int) -> Agent | None:
    """保留最早采纳副本，删除重复记录。"""
    rows = db.scalars(
        select(Agent)
        .where(Agent.owner_id == user_id, Agent.source_agent_id == source_id)
        .order_by(Agent.id)
    ).all()
    if not rows:
        return None
    keep = rows[0]
    for dup in rows[1:]:
        db.execute(delete(Material).where(Material.agent_id == dup.id))
        db.execute(delete(QuestionBank).where(QuestionBank.agent_id == dup.id))
        db.execute(delete(KnowledgePoint).where(KnowledgePoint.agent_id == dup.id))
        db.execute(delete(ExamConfig).where(ExamConfig.agent_id == dup.id))
        db.execute(delete(AgentClass).where(AgentClass.agent_id == dup.id))
        db.delete(dup)
    db.flush()
    return keep


def _assert_course(db: DBSession, course_id: int | None) -> None:
    if course_id is not None and not db.get(Course, course_id):
        raise HTTPException(404, "绑定课程不存在")


def _assert_agent_name_unique(db: DBSession, owner_id: int, name: str, exclude_id: int | None = None) -> None:
    name = (name or "").strip()
    if not name:
        return
    q = select(Agent).where(Agent.owner_id == owner_id, Agent.name == name)
    if exclude_id:
        q = q.where(Agent.id != exclude_id)
    if db.scalar(q):
        raise HTTPException(400, f"您已有同名智能体「{name}」")


def _enrich_agent_dict(db: DBSession, agent: Agent) -> dict:
    d = _agent_dict(agent, db)
    owner = db.get(User, agent.owner_id) if agent.owner_id else None
    d["owner_id"] = agent.owner_id
    d["owner_name"] = owner.display_name or owner.username if owner else ""
    d["source_agent_id"] = agent.source_agent_id
    d["is_adopted"] = bool(agent.source_agent_id)
    d["is_shared"] = bool(agent.is_shared)
    d["is_owner"] = False
    d["bound_class_ids"] = get_bound_class_ids(db, agent.id)
    d["shared_content_class_ids"] = get_shared_content_class_ids(db, agent)
    return d


def _adopter_count(db: DBSession, source_id: int) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(Agent).where(Agent.source_agent_id == source_id)
        )
        or 0
    )


def _list_adopters(db: DBSession, source_id: int) -> list[dict]:
    copies = db.scalars(
        select(Agent).where(Agent.source_agent_id == source_id).order_by(Agent.id.desc())
    ).all()
    out: list[dict] = []
    for a in copies:
        owner = db.get(User, a.owner_id) if a.owner_id else None
        bound_ids = get_bound_class_ids(db, a.id)
        class_names: list[str] = []
        for cid in bound_ids:
            tc = db.get(TeachingClass, cid)
            class_names.append(tc.name if tc else f"班级{cid}")
        out.append(
            {
                "adopted_agent_id": a.id,
                "adopted_agent_name": a.name,
                "status": a.status,
                "teacher_id": a.owner_id,
                "username": owner.username if owner else "",
                "display_name": (owner.display_name or owner.username) if owner else "未知教师",
                "bound_class_ids": bound_ids,
                "bound_class_names": class_names,
                "snapshot_at": a.source_snapshot_at.isoformat() if a.source_snapshot_at else None,
            }
        )
    return out


def _managed_bound_class_ids(db: DBSession, agent: Agent, user: User) -> list[int]:
    """仅返回当前教师有权管理的绑定班级（不写库，避免列表接口卡死）。"""
    bound = get_bound_class_ids(db, agent.id)
    if user.role != "teacher":
        return bound
    managed = set(get_managed_class_ids(db, user) or [])
    return [cid for cid in bound if cid in managed]


def _enrich_owned(
    db: DBSession,
    agent: Agent,
    user: CurrentUser,
    *,
    managed_ids: set[int] | None = None,
) -> dict:
    d = _enrich_agent_dict(db, agent)
    d["is_owner"] = agent.owner_id == user.id
    d["adopter_count"] = _adopter_count(db, agent.id)
    bound = get_bound_class_ids(db, agent.id)
    if managed_ids is not None:
        d["bound_class_ids"] = [cid for cid in bound if cid in managed_ids]
    else:
        d["bound_class_ids"] = _managed_bound_class_ids(db, agent, user)
    return d


@router.get("", dependencies=[Depends(require_role("teacher"))])
def list_my_agents(user: CurrentUser, db: DBSession) -> list[dict]:
    managed = set(get_managed_class_ids(db, user) or [])
    rows = db.scalars(
        select(Agent).where(Agent.owner_id == user.id).order_by(Agent.id)
    ).all()
    return [_enrich_owned(db, a, user, managed_ids=managed) for a in rows]


@router.get("/shared", dependencies=[Depends(require_role("teacher"))])
def list_shared_agents(
    user: CurrentUser,
    db: DBSession,
    slug: str | None = Query(default=None),
) -> list[dict]:
    from ..constants.agent_languages import LANG_FILTER_ALIASES

    q = select(Agent).where(
        Agent.is_shared.is_(True),
        Agent.status == "active",
    )
    if slug:
        slugs = LANG_FILTER_ALIASES.get(slug.strip().lower(), [slug.strip().lower()])
        q = q.where(Agent.slug.in_(slugs))
    rows = db.scalars(q.order_by(Agent.shared_at.desc(), Agent.id.desc())).all()
    result = []
    for a in rows:
        d = _enrich_agent_dict(db, a)
        d["is_owner"] = a.owner_id == user.id
        adopted = _find_adopted(db, user.id, a.id)
        d["already_adopted"] = adopted is not None
        d["adopted_agent_id"] = adopted.id if adopted else None
        d["adopter_count"] = _adopter_count(db, a.id) if a.owner_id == user.id else None
        result.append(d)
    return result


@router.get("/{agent_id}/adopters", dependencies=[Depends(require_role("teacher"))])
def list_adopters(agent_id: int, user: CurrentUser, db: DBSession) -> dict:
    """共享方查看谁采纳了该智能体（仅拥有者）。"""
    agent = assert_agent_owner(db, user, agent_id)
    items = _list_adopters(db, agent.id)
    return {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "is_shared": bool(agent.is_shared),
        "total": len(items),
        "items": items,
    }


@router.post("", status_code=201, dependencies=[Depends(require_role("teacher"))])
def create_agent(payload: TeacherAgentIn, user: CurrentUser, db: DBSession) -> dict:
    _assert_course(db, payload.course_id)
    _assert_agent_name_unique(db, user.id, payload.name)
    agent = Agent(
        name=payload.name,
        intro=payload.intro,
        endpoint="/api/agents/course/ask",
        course_id=payload.course_id,
        slug=payload.slug,
        status=payload.status,
        owner_id=user.id,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return _enrich_owned(db, agent, user)


@router.put("/{agent_id}", dependencies=[Depends(require_role("teacher"))])
def update_agent(agent_id: int, payload: TeacherAgentIn, user: CurrentUser, db: DBSession) -> dict:
    agent = assert_agent_owner(db, user, agent_id)
    _assert_course(db, payload.course_id)
    _assert_agent_name_unique(db, user.id, payload.name, exclude_id=agent_id)
    agent.name = payload.name
    agent.intro = payload.intro
    agent.course_id = payload.course_id
    agent.slug = (payload.slug or "").strip().lower()
    if payload.status != "active" and agent.is_shared:
        agent.is_shared = False
        agent.shared_at = None
    agent.status = payload.status
    db.commit()
    db.refresh(agent)
    return _enrich_owned(db, agent, user)


@router.delete("/{agent_id}", dependencies=[Depends(require_role("teacher"))])
def delete_agent(agent_id: int, user: CurrentUser, db: DBSession) -> dict:
    agent = assert_agent_owner(db, user, agent_id)
    if agent.is_shared:
        adopters = db.scalars(
            select(Agent.id).where(Agent.source_agent_id == agent.id)
        ).all()
        if adopters:
            raise HTTPException(400, "该智能体已被他人采纳，请先取消共享后再删除")
    db.delete(agent)
    db.commit()
    return {"ok": True}


@router.put("/{agent_id}/classes", dependencies=[Depends(require_role("teacher"))])
def bind_classes(agent_id: int, payload: AgentClassesIn, user: CurrentUser, db: DBSession) -> dict:
    agent = assert_agent_owner(db, user, agent_id)
    managed = set(get_managed_class_ids(db, user) or [])
    if not managed:
        raise HTTPException(400, "您尚未管理任何班级")
    try:
        unique_ids = list(dict.fromkeys(int(cid) for cid in payload.class_ids))
    except (TypeError, ValueError):
        raise HTTPException(400, "班级 ID 无效")
    for cid in unique_ids:
        if cid not in managed:
            cls = db.get(TeachingClass, cid)
            label = cls.name if cls else f"ID {cid}"
            raise HTTPException(403, f"无权绑定班级「{label}」")
        if agent.course_id:
            cls = db.get(TeachingClass, cid)
            if cls and cls.course_id and cls.course_id != agent.course_id:
                raise HTTPException(400, f"智能体课程与班级「{cls.name}」课程不一致")

    existing_rows = db.scalars(
        select(AgentClass).where(AgentClass.agent_id == agent_id)
    ).all()
    existing_ids = {r.class_id for r in existing_rows}
    target_ids = set(unique_ids)
    for row in existing_rows:
        if row.class_id not in target_ids or row.class_id not in managed:
            db.delete(row)
    db.flush()

    for cid in unique_ids:
        if cid not in existing_ids:
            db.add(AgentClass(agent_id=agent_id, class_id=cid, assigned_by=user.id))
    # 对当前绑定的全部班级做幂等同步：补齐后增的快照模板 → 班级资料
    # （仅同步「新绑」会导致模板变多后班级行数仍偏少）
    index_ids: list[int] = []
    if unique_ids and agent.source_agent_id and agent.source_snapshot_at:
        index_ids = propagate_snapshot_to_classes(db, agent, unique_ids)
    db.commit()
    if index_ids:
        schedule_index_adopted_materials(index_ids)
    return {"ok": True, "bound_class_ids": unique_ids}


@router.post("/{agent_id}/share", dependencies=[Depends(require_role("teacher"))])
def set_share(agent_id: int, payload: ShareAgentIn, user: CurrentUser, db: DBSession) -> dict:
    agent = assert_agent_owner(db, user, agent_id)
    if payload.is_shared:
        if agent.status != "active":
            raise HTTPException(400, "仅已上线的智能体可共享到共享广场")
    agent.is_shared = payload.is_shared
    agent.shared_at = datetime.utcnow() if payload.is_shared else None
    db.commit()
    db.refresh(agent)
    return _enrich_owned(db, agent, user)


@router.post("/adopt/{source_id}", status_code=201, dependencies=[Depends(require_role("teacher"))])
def adopt_agent(source_id: int, user: CurrentUser, db: DBSession) -> dict:
    source = db.get(Agent, source_id)
    if not source or not source.is_shared or source.status != "active":
        raise HTTPException(404, "共享智能体不存在或未开放共享")
    if source.owner_id == user.id:
        raise HTTPException(400, "不能采纳自己的智能体")

    existing = _dedupe_adopted_copies(db, user.id, source_id)
    if existing:
        material_ids: list[int] = []
        if not existing.source_snapshot_at:
            material_ids = clone_agent_content_snapshot(db, source, existing)
        else:
            repair_adopted_chapter_links(db, existing)
        db.commit()
        db.refresh(existing)
        if material_ids:
            schedule_index_adopted_materials(material_ids)
        return _enrich_owned(db, existing, user)

    slug = source.slug or f"adopted-{source_id}"
    base_slug = slug
    n = 1
    while db.scalar(select(Agent).where(Agent.owner_id == user.id, Agent.slug == slug)):
        slug = f"{base_slug}-{n}"
        n += 1

    agent = Agent(
        name=source.name,
        intro=source.intro,
        endpoint=source.endpoint or "/api/agents/course/ask",
        course_id=source.course_id,
        slug=slug,
        status="planned",
        owner_id=user.id,
        source_agent_id=source.id,
    )
    db.add(agent)
    db.flush()
    material_ids = clone_agent_content_snapshot(db, source, agent)
    db.commit()
    db.refresh(agent)
    if material_ids:
        schedule_index_adopted_materials(material_ids)
    return _enrich_owned(db, agent, user)
