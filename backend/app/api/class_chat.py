"""班级课程群聊：公开群消息、教师话题讨论、师生私信。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, or_, select

from ..deps import CurrentUser, DBSession
from ..models import (
    Chapter,
    ClassChatDm,
    ClassChatMessage,
    ClassChatRead,
    KnowledgePoint,
    TeachingClass,
    User,
)
from ..services.class_chat_access import (
    assert_class_chat_member,
    assert_dm_peer_allowed,
    list_class_student_users,
    list_class_teacher_users,
)

router = APIRouter(prefix="/classes/{class_id}/chat", tags=["class-chat"])

MAX_CONTENT = 2000
MAX_TITLE = 120


class TextBody(BaseModel):
    content: str = Field(..., min_length=1, max_length=MAX_CONTENT)


class TopicBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE)
    content: str = Field("", max_length=MAX_CONTENT)
    knowledge_point_id: int | None = None


class DmBody(BaseModel):
    receiver_id: int
    content: str = Field(..., min_length=1, max_length=MAX_CONTENT)


class ReadBody(BaseModel):
    channel: str = Field(..., min_length=1, max_length=64)
    last_read_message_id: int = Field(..., ge=0)


def _sender_fields(u: User | None) -> dict:
    if not u:
        return {"sender_id": 0, "sender_name": "未知", "sender_role": ""}
    return {
        "sender_id": u.id,
        "sender_name": u.display_name or u.username,
        "sender_role": u.role,
    }


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _msg_out(m: ClassChatMessage, sender: User | None = None, kp_name: str | None = None) -> dict:
    s = sender or m.sender
    out = {
        "id": m.id,
        "class_id": m.class_id,
        "msg_type": m.msg_type,
        "content": m.content or "",
        "title": m.title,
        "parent_id": m.parent_id,
        "knowledge_point_id": m.knowledge_point_id,
        "knowledge_point_name": kp_name,
        "created_at": _iso(m.created_at),
        **_sender_fields(s),
    }
    return out


def _dm_out(m: ClassChatDm, sender: User | None = None) -> dict:
    s = sender or m.sender
    return {
        "id": m.id,
        "class_id": m.class_id,
        "receiver_id": m.receiver_id,
        "content": m.content or "",
        "created_at": _iso(m.created_at),
        "read_at": _iso(m.read_at),
        **_sender_fields(s),
    }


def _user_brief(u: User) -> dict:
    return {
        "id": u.id,
        "display_name": u.display_name or u.username,
        "username": u.username,
        "role": u.role,
    }


def _load_senders(db, ids: set[int]) -> dict[int, User]:
    if not ids:
        return {}
    rows = db.scalars(select(User).where(User.id.in_(ids))).all()
    return {u.id: u for u in rows}


def _validate_kp(db, class_id: int, kp_id: int | None) -> KnowledgePoint | None:
    if kp_id is None:
        return None
    kp = db.get(KnowledgePoint, kp_id)
    if not kp:
        raise HTTPException(400, "知识点不存在")
    cls = db.get(TeachingClass, class_id)
    if not cls:
        raise HTTPException(404, "班级不存在")
    # 允许：同班知识点，或同课程章节下的知识点
    if kp.class_id and kp.class_id == class_id:
        return kp
    ch = db.get(Chapter, kp.chapter_id)
    if ch and cls.course_id and ch.course_id == cls.course_id:
        return kp
    raise HTTPException(400, "知识点不属于本班/本课")


# ---------- 群公开消息 ----------

@router.get("/messages")
def list_messages(
    class_id: int,
    user: CurrentUser,
    db: DBSession,
    after_id: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    assert_class_chat_member(db, user, class_id)
    q = (
        select(ClassChatMessage)
        .where(ClassChatMessage.class_id == class_id)
        .where(ClassChatMessage.msg_type.in_(("text", "topic")))
    )
    if after_id > 0:
        q = q.where(ClassChatMessage.id > after_id).order_by(ClassChatMessage.id.asc())
        rows = list(db.scalars(q.limit(limit)).all())
    else:
        rows = list(db.scalars(q.order_by(desc(ClassChatMessage.id)).limit(limit)).all())
        rows.reverse()

    senders = _load_senders(db, {m.sender_id for m in rows})
    kp_ids = {m.knowledge_point_id for m in rows if m.knowledge_point_id}
    kps = {}
    if kp_ids:
        kps = {k.id: k.name for k in db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(kp_ids))).all()}
    return {
        "items": [
            _msg_out(m, senders.get(m.sender_id), kps.get(m.knowledge_point_id) if m.knowledge_point_id else None)
            for m in rows
        ]
    }


@router.post("/messages")
def post_message(class_id: int, body: TextBody, user: CurrentUser, db: DBSession) -> dict:
    assert_class_chat_member(db, user, class_id)
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "消息不能为空")
    m = ClassChatMessage(
        class_id=class_id,
        sender_id=user.id,
        msg_type="text",
        content=content,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _msg_out(m, user)


# ---------- 话题 ----------

@router.get("/topics")
def list_topics(class_id: int, user: CurrentUser, db: DBSession) -> dict:
    assert_class_chat_member(db, user, class_id)
    rows = list(db.scalars(
        select(ClassChatMessage)
        .where(
            ClassChatMessage.class_id == class_id,
            ClassChatMessage.msg_type == "topic",
        )
        .order_by(desc(ClassChatMessage.id))
        .limit(100)
    ).all())
    senders = _load_senders(db, {m.sender_id for m in rows})
    kp_ids = {m.knowledge_point_id for m in rows if m.knowledge_point_id}
    kps = {}
    if kp_ids:
        kps = {k.id: k.name for k in db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(kp_ids))).all()}

    reply_counts: dict[int, int] = {}
    if rows:
        from sqlalchemy import func
        counts = db.execute(
            select(ClassChatMessage.parent_id, func.count())
            .where(
                ClassChatMessage.class_id == class_id,
                ClassChatMessage.msg_type == "topic_reply",
                ClassChatMessage.parent_id.in_([m.id for m in rows]),
            )
            .group_by(ClassChatMessage.parent_id)
        ).all()
        reply_counts = {pid: n for pid, n in counts if pid}

    items = []
    for m in rows:
        item = _msg_out(m, senders.get(m.sender_id), kps.get(m.knowledge_point_id) if m.knowledge_point_id else None)
        item["reply_count"] = reply_counts.get(m.id, 0)
        items.append(item)
    return {"items": items}


@router.post("/topics")
def create_topic(class_id: int, body: TopicBody, user: CurrentUser, db: DBSession) -> dict:
    assert_class_chat_member(db, user, class_id)
    if user.role not in ("teacher", "admin"):
        raise HTTPException(403, "仅教师可发布话题")
    title = body.title.strip()
    content = (body.content or "").strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    kp = _validate_kp(db, class_id, body.knowledge_point_id)
    m = ClassChatMessage(
        class_id=class_id,
        sender_id=user.id,
        msg_type="topic",
        title=title,
        content=content,
        knowledge_point_id=kp.id if kp else None,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _msg_out(m, user, kp.name if kp else None)


@router.get("/topics/{topic_id}/replies")
def list_replies(
    class_id: int,
    topic_id: int,
    user: CurrentUser,
    db: DBSession,
    after_id: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    assert_class_chat_member(db, user, class_id)
    topic = db.get(ClassChatMessage, topic_id)
    if not topic or topic.class_id != class_id or topic.msg_type != "topic":
        raise HTTPException(404, "话题不存在")
    q = (
        select(ClassChatMessage)
        .where(
            ClassChatMessage.class_id == class_id,
            ClassChatMessage.msg_type == "topic_reply",
            ClassChatMessage.parent_id == topic_id,
        )
    )
    if after_id > 0:
        q = q.where(ClassChatMessage.id > after_id).order_by(ClassChatMessage.id.asc())
        rows = list(db.scalars(q.limit(limit)).all())
    else:
        rows = list(db.scalars(q.order_by(ClassChatMessage.id.asc()).limit(limit)).all())
    senders = _load_senders(db, {m.sender_id for m in rows})
    kp_name = None
    if topic.knowledge_point_id:
        kp = db.get(KnowledgePoint, topic.knowledge_point_id)
        kp_name = kp.name if kp else None
    return {
        "topic": _msg_out(topic, db.get(User, topic.sender_id), kp_name),
        "items": [_msg_out(m, senders.get(m.sender_id)) for m in rows],
    }


@router.post("/topics/{topic_id}/replies")
def post_reply(
    class_id: int,
    topic_id: int,
    body: TextBody,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    assert_class_chat_member(db, user, class_id)
    topic = db.get(ClassChatMessage, topic_id)
    if not topic or topic.class_id != class_id or topic.msg_type != "topic":
        raise HTTPException(404, "话题不存在")
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "回复不能为空")
    m = ClassChatMessage(
        class_id=class_id,
        sender_id=user.id,
        msg_type="topic_reply",
        content=content,
        parent_id=topic_id,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _msg_out(m, user)


@router.get("/knowledge-points")
def list_chat_knowledge_points(class_id: int, user: CurrentUser, db: DBSession) -> dict:
    """话题可选知识点（本班或本课章节下）。"""
    cls = assert_class_chat_member(db, user, class_id)
    q = select(KnowledgePoint)
    if cls.course_id:
        chapter_ids = list(db.scalars(
            select(Chapter.id).where(Chapter.course_id == cls.course_id)
        ).all())
        if chapter_ids:
            q = q.where(
                or_(
                    KnowledgePoint.class_id == class_id,
                    KnowledgePoint.chapter_id.in_(chapter_ids),
                )
            )
        else:
            q = q.where(KnowledgePoint.class_id == class_id)
    else:
        q = q.where(KnowledgePoint.class_id == class_id)
    rows = list(db.scalars(q.order_by(KnowledgePoint.id).limit(300)).all())
    return {"items": [{"id": k.id, "name": k.name, "chapter_id": k.chapter_id} for k in rows]}


# ---------- 私信 ----------

@router.get("/teachers")
def list_teachers(class_id: int, user: CurrentUser, db: DBSession) -> dict:
    assert_class_chat_member(db, user, class_id)
    return {"items": [_user_brief(u) for u in list_class_teacher_users(db, class_id)]}


@router.get("/students")
def list_students(class_id: int, user: CurrentUser, db: DBSession) -> dict:
    assert_class_chat_member(db, user, class_id)
    if user.role not in ("teacher", "admin"):
        raise HTTPException(403, "仅教师可查看学生列表")
    return {"items": [_user_brief(u) for u in list_class_student_users(db, class_id)]}


@router.get("/dms")
def list_dms(
    class_id: int,
    user: CurrentUser,
    db: DBSession,
    peer_id: int = Query(...),
    after_id: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    assert_class_chat_member(db, user, class_id)
    assert_dm_peer_allowed(db, user, class_id, peer_id)
    cond = and_(
        ClassChatDm.class_id == class_id,
        or_(
            and_(ClassChatDm.sender_id == user.id, ClassChatDm.receiver_id == peer_id),
            and_(ClassChatDm.sender_id == peer_id, ClassChatDm.receiver_id == user.id),
        ),
    )
    q = select(ClassChatDm).where(cond)
    if after_id > 0:
        q = q.where(ClassChatDm.id > after_id).order_by(ClassChatDm.id.asc())
        rows = list(db.scalars(q.limit(limit)).all())
    else:
        rows = list(db.scalars(q.order_by(desc(ClassChatDm.id)).limit(limit)).all())
        rows.reverse()
    senders = _load_senders(db, {m.sender_id for m in rows})
    # 标记对方发来的未读为已读
    now = datetime.utcnow()
    for m in rows:
        if m.receiver_id == user.id and m.read_at is None:
            m.read_at = now
    db.commit()
    return {"items": [_dm_out(m, senders.get(m.sender_id)) for m in rows]}


@router.post("/dms")
def post_dm(class_id: int, body: DmBody, user: CurrentUser, db: DBSession) -> dict:
    assert_class_chat_member(db, user, class_id)
    assert_dm_peer_allowed(db, user, class_id, body.receiver_id)
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "消息不能为空")
    m = ClassChatDm(
        class_id=class_id,
        sender_id=user.id,
        receiver_id=body.receiver_id,
        content=content,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _dm_out(m, user)


# ---------- 已读 ----------

@router.post("/read")
def mark_read(class_id: int, body: ReadBody, user: CurrentUser, db: DBSession) -> dict:
    assert_class_chat_member(db, user, class_id)
    channel = body.channel.strip()
    if not channel:
        raise HTTPException(400, "channel 无效")
    row = db.scalar(
        select(ClassChatRead).where(
            ClassChatRead.user_id == user.id,
            ClassChatRead.class_id == class_id,
            ClassChatRead.channel == channel,
        )
    )
    if not row:
        row = ClassChatRead(
            user_id=user.id,
            class_id=class_id,
            channel=channel,
            last_read_message_id=body.last_read_message_id,
        )
        db.add(row)
    else:
        if body.last_read_message_id > row.last_read_message_id:
            row.last_read_message_id = body.last_read_message_id
    db.commit()
    return {"ok": True, "channel": channel, "last_read_message_id": row.last_read_message_id}


@router.get("/unread")
def unread_summary(class_id: int, user: CurrentUser, db: DBSession) -> dict:
    assert_class_chat_member(db, user, class_id)
    group_read = db.scalar(
        select(ClassChatRead).where(
            ClassChatRead.user_id == user.id,
            ClassChatRead.class_id == class_id,
            ClassChatRead.channel == "group",
        )
    )
    last_group = group_read.last_read_message_id if group_read else 0
    from sqlalchemy import func
    group_unread = db.scalar(
        select(func.count())
        .select_from(ClassChatMessage)
        .where(
            ClassChatMessage.class_id == class_id,
            ClassChatMessage.msg_type.in_(("text", "topic")),
            ClassChatMessage.id > last_group,
            ClassChatMessage.sender_id != user.id,
        )
    ) or 0
    dm_unread = db.scalar(
        select(func.count())
        .select_from(ClassChatDm)
        .where(
            ClassChatDm.class_id == class_id,
            ClassChatDm.receiver_id == user.id,
            ClassChatDm.read_at.is_(None),
        )
    ) or 0
    return {"group": int(group_unread), "dm": int(dm_unread)}
