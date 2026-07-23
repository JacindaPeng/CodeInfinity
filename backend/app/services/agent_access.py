"""课程智能体可见性与混合检索权限。"""

from __future__ import annotations



from fastapi import HTTPException

from sqlalchemy import and_, or_, select

from sqlalchemy.orm import Session



from ..deps import get_exam_config, get_managed_class_ids

from ..models import Agent, AgentClass, Chapter, ExamConfig, Material, QuestionBank, User

from .chapter_sync import (
    C_LANG_COURSE_ID,
    agent_scoped_chapter_condition,
    is_original_c_lang_agent,
    requires_agent_scoped_chapters,
)
from .enrollment import assert_student_enrolled, get_student_class_for_course, get_student_class_ids





def get_bound_class_ids(db: Session, agent_id: int) -> list[int]:

    return list(db.scalars(

        select(AgentClass.class_id).where(AgentClass.agent_id == agent_id)

    ).all())





def get_teacher_agent_bound_classes(db: Session, user: User, agent_id: int) -> list[int]:

    """教师在某智能体下可选班级 = 所管班级 ∩ 智能体绑定班级。"""

    bound = set(get_bound_class_ids(db, agent_id))

    if user.role != "teacher":

        return sorted(bound)

    managed = set(get_managed_class_ids(db, user) or [])

    return sorted(managed & bound)





def assert_teacher_class_bound_to_agent(

    db: Session, user: User, agent_id: int, class_id: int,

) -> None:

    if user.role != "teacher":

        return

    if class_id not in get_teacher_agent_bound_classes(db, user, agent_id):

        raise HTTPException(403, "该班级未绑定当前智能体")





def get_visible_agent_ids(db: Session, user: User) -> set[int]:

    """当前用户可见的智能体 ID（教学侧列表/访问）。"""

    if user.role == "admin":

        return set(db.scalars(select(Agent.id)).all())



    visible: set[int] = set()



    if user.role == "teacher":

        owned = db.scalars(select(Agent.id).where(Agent.owner_id == user.id)).all()

        visible.update(owned)

        managed = get_managed_class_ids(db, user) or []

        if managed:

            bound = db.scalars(

                select(AgentClass.agent_id).where(AgentClass.class_id.in_(managed))

            ).all()

            visible.update(bound)



    if user.role == "student":

        class_ids = get_student_class_ids(db, user)

        if not class_ids and user.class_id:

            class_ids = [user.class_id]

        if class_ids:

            bound = db.scalars(

                select(AgentClass.agent_id)

                .join(Agent, Agent.id == AgentClass.agent_id)

                .where(

                    AgentClass.class_id.in_(class_ids),

                    Agent.status == "active",

                )

            ).all()

            visible.update(bound)



    return visible





def assert_agent_access(db: Session, user: User, agent_id: int) -> Agent:

    agent = db.get(Agent, agent_id)

    if not agent:

        raise HTTPException(404, "智能体不存在")

    if agent_id in get_visible_agent_ids(db, user):

        return agent

    if (

        user.role == "teacher"

        and agent.is_shared

        and agent.status == "active"

    ):

        return agent

    raise HTTPException(403, "无权访问该智能体")





def assert_agent_owner(db: Session, user: User, agent_id: int) -> Agent:

    if user.role != "teacher":

        raise HTTPException(403, "仅教师可管理智能体")

    agent = db.get(Agent, agent_id)

    if not agent:

        raise HTTPException(404, "智能体不存在")

    if agent.owner_id != user.id:

        raise HTTPException(403, "仅智能体拥有者可操作")

    return agent


def can_teacher_manage_agent_content(db: Session, user: User, agent_id: int) -> bool:
    """智能体拥有者，或管理该智能体已绑定班级的任课教师，可维护资料/题库等教学内容。"""
    if user.role == "admin":
        return True
    if user.role != "teacher":
        return False
    agent = db.get(Agent, agent_id)
    if not agent:
        return False
    if agent.owner_id == user.id:
        return True
    return bool(get_teacher_agent_bound_classes(db, user, agent_id))


def assert_teacher_can_manage_agent_content(db: Session, user: User, agent_id: int) -> Agent:
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    if user.role == "admin":
        return agent
    if user.role != "teacher":
        raise HTTPException(403, "仅教师可管理智能体内容")
    if agent.owner_id == user.id:
        return agent
    if get_teacher_agent_bound_classes(db, user, agent_id):
        return agent
    raise HTTPException(403, "仅智能体拥有者或已绑定班级的任课教师可操作")





def is_adopted_snapshot(agent: Agent | None) -> bool:

    """已采纳且已快照：内容与源智能体解耦，不再随共享源变化。"""

    return bool(agent and agent.source_agent_id and agent.source_snapshot_at)





def apply_agent_chapter_scope(

    query,

    db: Session,

    course_id: int | None,

    agent_id: int | None,

):

    """章节列表隔离：预置 C 智能体看全课程章节，其余仅看本智能体内容。"""

    if course_id is None or not requires_agent_scoped_chapters(db, course_id, agent_id):

        return query

    if agent_id is None:

        return None

    return query.where(agent_scoped_chapter_condition(db, course_id, agent_id))





def _material_class_ids_for_agent(db: Session, agent: Agent) -> list[int]:

    """智能体关联课程资料所在的班级 ID。"""

    rows = db.scalars(

        select(Material.class_id)

        .where(Material.agent_id == agent.id, Material.class_id.isnot(None))

        .distinct()

    ).all()

    return list(rows)





def get_shared_content_agent(db: Session, agent: Agent | None) -> Agent | None:

    """返回提供共享资料/题库的源智能体（仅预览未采纳时；已采纳副本不再关联源）。"""

    if not agent:

        return None

    if agent.source_agent_id:

        return None

    if agent.is_shared and agent.status == "active":

        return agent

    return None





def get_shared_content_class_ids(db: Session, agent: Agent | None) -> list[int]:

    content = get_shared_content_agent(db, agent)

    if not content:

        return []

    ids = set(_material_class_ids_for_agent(db, content))

    qb_ids = db.scalars(

        select(QuestionBank.class_id)

        .where(QuestionBank.agent_id == content.id, QuestionBank.class_id.isnot(None))

        .distinct()

    ).all()

    ids.update(qb_ids)

    # 源智能体已绑定班级也算可读标签范围（资料可能挂在绑定班）

    ids.update(get_bound_class_ids(db, content.id))

    return sorted(ids)


def is_shared_agent_preview(agent: Agent | None, user: User) -> bool:

    """教师正在体验他人已共享、且本人未采纳的源智能体。"""

    return bool(

        agent

        and user.role == "teacher"

        and agent.is_shared

        and agent.status == "active"

        and agent.owner_id != user.id

        and not agent.source_agent_id

    )





def get_agent_for_class_course(

    db: Session, class_id: int, course_id: int | None,

) -> Agent | None:

    """班级绑定的课程智能体（优先采纳副本）。"""

    q = (

        select(Agent)

        .join(AgentClass, AgentClass.agent_id == Agent.id)

        .where(AgentClass.class_id == class_id)

    )

    if course_id is not None:

        q = q.where(Agent.course_id == course_id)

    agents = db.scalars(q).all()

    for a in agents:

        if a.source_agent_id:

            return a

    for a in agents:

        if a.status == "active":

            return a

    return agents[0] if agents else None





def resolve_agent_for_exam(

    db: Session,

    user: User,

    class_id: int,

    course_id: int | None,

    agent_id: int | None = None,

) -> Agent | None:

    if agent_id:

        return assert_agent_access(db, user, agent_id)

    return get_agent_for_class_course(db, class_id, course_id)





def resolve_resource_class_ids_for_agent(
    db: Session,
    user: User,
    class_id: int | None = None,
    agent_id: int | None = None,
) -> list[int] | None:
    """资料/题库可见班级：本班 + 共享智能体源班级（已采纳副本仅用本班）。"""
    from ..deps import resolve_resource_class_ids

    if not agent_id:
        return resolve_resource_class_ids(db, user, class_id)

    agent = assert_agent_access(db, user, agent_id)

    if user.role == "teacher":
        bound = get_teacher_agent_bound_classes(db, user, agent_id)
        shared_preview = is_shared_agent_preview(agent, user)
        shared_ids = get_shared_content_class_ids(db, agent) if shared_preview else []

        if class_id is not None:
            # 先判断绑定/共享可读，勿调用 resolve_resource_class_ids(class_id)：
            # 体验他人共享时 class_id 往往不在本人所管班级，会提前 403。
            if class_id in bound:
                return [class_id]
            if shared_preview and class_id in shared_ids:
                return [class_id]
            raise HTTPException(403, "该班级未绑定当前智能体")

        if bound:
            return bound
        if shared_preview:
            # 无绑定也无源班级标签时不按班级过滤，仍可看本智能体模板资料
            return shared_ids if shared_ids else None
        if is_adopted_snapshot(agent) and agent.owner_id == user.id:
            return None
        return []

    base = resolve_resource_class_ids(db, user, class_id)
    if is_adopted_snapshot(agent):
        return base

    extra = get_shared_content_class_ids(db, agent)
    if not extra:
        return base
    return list(dict.fromkeys([*(base or []), *extra]))




def apply_agent_content_scope(
    model,
    query,
    agent: Agent | None,
    allowed_classes: list[int] | None,
    db: Session | None = None,
):
    """按智能体与班级过滤资料/题库；预置 C 智能体可见 agent_id 为空的历史数据。"""
    from sqlalchemy import and_

    if agent and is_adopted_snapshot(agent):
        # 采纳副本：已绑定班级时只展示班级资料（不展示 class_id 为空的快照模板）
        if allowed_classes is not None and allowed_classes:
            return query.where(
                model.agent_id == agent.id,
                model.class_id.in_(allowed_classes),
            )
        # 尚未绑定：展示模板资料，便于确认快照内容
        return query.where(model.agent_id == agent.id)

    if agent and db:
        if is_original_c_lang_agent(db, agent):
            query = query.where(or_(
                model.agent_id == agent.id,
                model.agent_id.is_(None),
            ))
        elif requires_agent_scoped_chapters(db, agent.course_id or 0, agent.id):
            query = query.where(model.agent_id == agent.id)

    if allowed_classes is not None:
        if not allowed_classes:
            return None
        # 班级资料 + 本智能体 class_id 为空的共享模板
        if agent is not None:
            return query.where(or_(
                model.class_id.in_(allowed_classes),
                and_(model.class_id.is_(None), model.agent_id == agent.id),
            ))
        return query.where(model.class_id.in_(allowed_classes))
    return query




def resolve_bank_class_ids(

    db: Session, agent: Agent | None, effective_class_id: int,

) -> list[int]:

    """考核抽题班级范围：本班 + 共享源班级（已采纳副本仅本班）。"""

    if is_adopted_snapshot(agent):

        return [effective_class_id]

    ids = [effective_class_id, *get_shared_content_class_ids(db, agent)]

    return list(dict.fromkeys(ids))





def get_shared_exam_config(

    db: Session,

    chapter_id: int,

    class_id: int,

    agent: Agent | None,

):

    """考核配置：本班优先，否则回退到共享源或采纳快照。"""

    cfg = get_exam_config(db, chapter_id, class_id)

    if cfg:

        return cfg

    if is_adopted_snapshot(agent):

        return db.scalar(

            select(ExamConfig)

            .where(

                ExamConfig.chapter_id == chapter_id,

                ExamConfig.agent_id == agent.id,

                or_(ExamConfig.class_id == class_id, ExamConfig.class_id.is_(None)),

            )

            .order_by(ExamConfig.class_id.desc())

        )

    for cid in get_shared_content_class_ids(db, agent):

        if cid == class_id:

            continue

        cfg = get_exam_config(db, chapter_id, cid)

        if cfg:

            return cfg

    return None





def resolve_retrieval_agent_id(db: Session, agent: Agent | None) -> int | None:

    """已采纳快照且尚无班级资料索引时，按 agent_id 检索向量库。"""

    if is_adopted_snapshot(agent):

        has_class_material = db.scalar(

            select(Material.id).where(

                Material.agent_id == agent.id,

                Material.class_id.isnot(None),

            ).limit(1)

        )

        if not has_class_material:

            return agent.id

    return None





def resolve_retrieval_class_ids(

    db: Session,

    agent: Agent | None,

    user: User,

    class_id: int | None,

) -> list[int] | None:

    """混合检索：本班资料 + 源共享智能体资料班级并集（已采纳副本不含源班级）。"""

    if user.role == "admin":

        if class_id:

            return [class_id]

        return None



    local: set[int] = set()

    if class_id:

        local.add(class_id)

    elif user.role == "student":

        if agent and agent.course_id:

            cid = get_student_class_for_course(db, user, agent.course_id)

            if cid:

                local.add(cid)

        elif class_id:

            assert_student_enrolled(db, user, class_id)

            local.add(class_id)

    elif user.role == "teacher":

        if agent:

            bound = get_teacher_agent_bound_classes(db, user, agent.id)

            shared_preview = is_shared_agent_preview(agent, user)

            shared_ids = get_shared_content_class_ids(db, agent) if shared_preview else []

            if class_id:

                if class_id in bound or (shared_preview and class_id in shared_ids):

                    local.add(class_id)

                else:

                    raise HTTPException(403, "该班级未绑定当前智能体")

            elif len(bound) == 1:

                local.add(bound[0])

            elif shared_preview:

                local.update(shared_ids)

        else:

            managed = get_managed_class_ids(db, user) or []

            if class_id and class_id in managed:

                local.add(class_id)

            elif len(managed) == 1:

                local.add(managed[0])



    if agent and not is_adopted_snapshot(agent) and not is_shared_agent_preview(agent, user):

        local.update(get_shared_content_class_ids(db, agent))



    if not local:

        return []

    return list(local)

