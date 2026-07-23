"""知识推送 API：未读角标、今日列表、已读、白名单源、手动跑一轮。"""
from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..deps import CurrentUser, DBSession, require_role
from ..models import Agent, Course, KnowledgeArticle, KnowledgePush, KnowledgeSource, User
from ..services.knowledge_fetch_service import (
    fetch_all_sources,
    upsert_bestblogs_whitelist,
)
from ..services.knowledge_push_service import push_for_user_now

router = APIRouter(prefix="/knowledge-push", tags=["knowledge-push"])


def _push_out(p: KnowledgePush, article: KnowledgeArticle | None = None) -> dict:
    art = article or p.article
    return {
        "id": p.id,
        "status": p.status,
        "reason": p.reason,
        "kp_names": p.kp_names_json or [],
        "agent_id": p.agent_id,
        "course_id": p.course_id,
        "pushed_at": p.pushed_at.isoformat() if p.pushed_at else None,
        "read_at": p.read_at.isoformat() if p.read_at else None,
        "article": {
            "id": art.id if art else None,
            "title": art.title if art else "",
            "summary": art.summary if art else "",
            "url": art.url if art else "",
            "published_at": art.published_at.isoformat() if art and art.published_at else None,
            "source_name": art.source.name if art and art.source else "",
            "resource_type": (art.resource_type or "article") if art else "article",
        },
    }


@router.get("/admin/stats", dependencies=[Depends(require_role("admin"))])
def admin_stats(_u: CurrentUser, db: DBSession) -> dict:
    total = db.scalar(select(func.count()).select_from(KnowledgePush)) or 0
    unread = db.scalar(
        select(func.count()).select_from(KnowledgePush).where(KnowledgePush.status == "unread")
    ) or 0
    read_n = db.scalar(
        select(func.count()).select_from(KnowledgePush).where(KnowledgePush.status == "read")
    ) or 0
    dismissed = db.scalar(
        select(func.count()).select_from(KnowledgePush).where(KnowledgePush.status == "dismissed")
    ) or 0
    articles = db.scalar(select(func.count()).select_from(KnowledgeArticle)) or 0
    sources = db.scalar(
        select(func.count()).select_from(KnowledgeSource).where(KnowledgeSource.enabled.is_(True))
    ) or 0
    since = datetime.utcnow() - timedelta(days=1)
    last_24h = db.scalar(
        select(func.count())
        .select_from(KnowledgePush)
        .where(KnowledgePush.pushed_at >= since)
    ) or 0
    return {
        "total": total,
        "unread": unread,
        "read": read_n,
        "dismissed": dismissed,
        "articles": articles,
        "enabled_sources": sources,
        "pushes_last_24h": last_24h,
    }


@router.get("/admin/records", dependencies=[Depends(require_role("admin"))])
def admin_records(
    _u: CurrentUser,
    db: DBSession,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    course_id: int | None = Query(default=None),
    q: str | None = Query(default=None, description="按学生姓名/用户名或文章标题模糊搜"),
) -> dict:
    base = select(KnowledgePush)
    count_q = select(func.count()).select_from(KnowledgePush)
    if status:
        base = base.where(KnowledgePush.status == status)
        count_q = count_q.where(KnowledgePush.status == status)
    if user_id is not None:
        base = base.where(KnowledgePush.user_id == user_id)
        count_q = count_q.where(KnowledgePush.user_id == user_id)
    if course_id is not None:
        base = base.where(KnowledgePush.course_id == course_id)
        count_q = count_q.where(KnowledgePush.course_id == course_id)
    if q and q.strip():
        kw = f"%{q.strip()}%"
        user_ids = list(
            db.scalars(
                select(User.id).where(
                    (User.username.ilike(kw)) | (User.display_name.ilike(kw))
                )
            ).all()
        )
        art_ids = list(
            db.scalars(
                select(KnowledgeArticle.id).where(KnowledgeArticle.title.ilike(kw))
            ).all()
        )
        conds = []
        if user_ids:
            conds.append(KnowledgePush.user_id.in_(user_ids))
        if art_ids:
            conds.append(KnowledgePush.article_id.in_(art_ids))
        if not conds:
            return {"items": [], "total": 0, "page": page, "size": size}
        from sqlalchemy import or_

        base = base.where(or_(*conds))
        count_q = count_q.where(or_(*conds))

    total = db.scalar(count_q) or 0
    rows = db.scalars(
        base.order_by(KnowledgePush.pushed_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()

    user_map = {
        u.id: u
        for u in db.scalars(
            select(User).where(User.id.in_({p.user_id for p in rows} or {0}))
        ).all()
    }
    course_map = {
        c.id: c.name
        for c in db.scalars(
            select(Course).where(Course.id.in_({p.course_id for p in rows if p.course_id} or {0}))
        ).all()
    }
    agent_map = {
        a.id: a.name
        for a in db.scalars(
            select(Agent).where(Agent.id.in_({p.agent_id for p in rows if p.agent_id} or {0}))
        ).all()
    }

    items = []
    for p in rows:
        u = user_map.get(p.user_id)
        item = _push_out(p)
        item.update(
            {
                "user_id": p.user_id,
                "username": u.username if u else "",
                "display_name": (u.display_name or u.username) if u else "",
                "course_name": course_map.get(p.course_id or 0, ""),
                "agent_name": agent_map.get(p.agent_id or 0, ""),
            }
        )
        items.append(item)
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/unread-count")
def unread_count(
    user: CurrentUser,
    db: DBSession,
    agent_id: int | None = Query(default=None),
    course_id: int | None = Query(default=None),
) -> dict:
    q = select(func.count()).select_from(KnowledgePush).where(
        KnowledgePush.user_id == user.id,
        KnowledgePush.status == "unread",
    )
    if agent_id is not None:
        q = q.where(KnowledgePush.agent_id == agent_id)
    if course_id is not None:
        q = q.where(KnowledgePush.course_id == course_id)
    n = db.scalar(q) or 0
    return {"count": n}


@router.get("/today")
def list_today(
    user: CurrentUser,
    db: DBSession,
    agent_id: int | None = Query(default=None),
    course_id: int | None = Query(default=None),
    include_read: bool = Query(default=True),
    resource_type: str = Query(default="all"),
) -> list[dict]:
    # 纠正历史误标（如把 python 当成薄弱点）
    from ..services.knowledge_push_service import (
        _sanitize_false_weak_reasons,
        _weak_keyword_set,
    )
    from ..services.weakness_service import resolve_student_weak_targets

    targets = resolve_student_weak_targets(db, user, all_courses=True)
    if _sanitize_false_weak_reasons(db, user.id, _weak_keyword_set(targets)):
        db.commit()

    since = datetime.utcnow() - timedelta(days=7)
    q = (
        select(KnowledgePush)
        .where(
            KnowledgePush.user_id == user.id,
            KnowledgePush.pushed_at >= since,
            KnowledgePush.status != "dismissed",
        )
        .order_by(KnowledgePush.pushed_at.desc())
        .limit(100)
    )
    if not include_read:
        q = q.where(KnowledgePush.status == "unread")
    if agent_id is not None:
        q = q.where(KnowledgePush.agent_id == agent_id)
    if course_id is not None:
        q = q.where(KnowledgePush.course_id == course_id)
    if resource_type != "all":
        if resource_type not in ("article", "podcast", "video", "twitter"):
            raise HTTPException(400, "不支持的资源类型")
        article_ids = select(KnowledgeArticle.id).where(
            KnowledgeArticle.resource_type == resource_type
        )
        q = q.where(KnowledgePush.article_id.in_(article_ids))
    rows = db.scalars(q).all()
    return [_push_out(p) for p in rows]


@router.post("/{push_id}/read")
def mark_read(push_id: int, user: CurrentUser, db: DBSession) -> dict:
    p = db.get(KnowledgePush, push_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "推送不存在")
    p.status = "read"
    p.read_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.post("/{push_id}/dismiss")
def dismiss(push_id: int, user: CurrentUser, db: DBSession) -> dict:
    p = db.get(KnowledgePush, push_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "推送不存在")
    p.status = "dismissed"
    p.read_at = p.read_at or datetime.utcnow()
    db.commit()
    return {"ok": True}


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    base_url: str = ""
    rss_url: str = Field(min_length=8, max_length=512)
    enabled: bool = True
    tags: str = ""
    resource_type: str = "article"


def _validated_resource_type(value: str) -> str:
    value = (value or "article").lower()
    if value not in ("article", "podcast", "video", "twitter"):
        raise HTTPException(400, "资源类型须为 article/podcast/video/twitter")
    return value


def _validated_http_url(value: str, field_name: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, f"{field_name} 必须是有效的 HTTP/HTTPS 地址")
    return value


@router.get("/sources", dependencies=[Depends(require_role("admin"))])
def list_sources(_u: CurrentUser, db: DBSession) -> list[dict]:
    rows = db.scalars(select(KnowledgeSource).order_by(KnowledgeSource.id)).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "base_url": s.base_url,
            "rss_url": s.rss_url,
            "enabled": s.enabled,
            "tags": s.tags,
            "resource_type": s.resource_type or "article",
        }
        for s in rows
    ]


@router.post("/sources", dependencies=[Depends(require_role("admin"))])
def create_source(payload: SourceIn, _u: CurrentUser, db: DBSession) -> dict:
    rss_url = _validated_http_url(payload.rss_url, "RSS 地址")
    base_url = (
        _validated_http_url(payload.base_url, "站点地址")
        if payload.base_url.strip()
        else ""
    )
    exists = db.scalar(
        select(KnowledgeSource.id).where(KnowledgeSource.rss_url == rss_url)
    )
    if exists:
        raise HTTPException(400, "该 RSS 已存在")
    s = KnowledgeSource(
        name=payload.name.strip(),
        base_url=base_url,
        rss_url=rss_url,
        enabled=payload.enabled,
        tags=payload.tags.strip(),
        resource_type=_validated_resource_type(payload.resource_type),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "ok": True}


@router.put("/sources/{source_id}", dependencies=[Depends(require_role("admin"))])
def update_source(source_id: int, payload: SourceIn, _u: CurrentUser, db: DBSession) -> dict:
    s = db.get(KnowledgeSource, source_id)
    if not s:
        raise HTTPException(404, "源不存在")
    rss_url = _validated_http_url(payload.rss_url, "RSS 地址")
    base_url = (
        _validated_http_url(payload.base_url, "站点地址")
        if payload.base_url.strip()
        else ""
    )
    duplicate = db.scalar(
        select(KnowledgeSource.id).where(
            KnowledgeSource.rss_url == rss_url,
            KnowledgeSource.id != source_id,
        )
    )
    if duplicate:
        raise HTTPException(400, "该 RSS 已存在")
    s.name = payload.name.strip()
    s.base_url = base_url
    s.rss_url = rss_url
    s.enabled = payload.enabled
    s.tags = payload.tags.strip()
    s.resource_type = _validated_resource_type(payload.resource_type)
    db.commit()
    return {"ok": True}


@router.post("/sources/import-bestblogs", dependencies=[Depends(require_role("admin"))])
def import_bestblogs_sources(_u: CurrentUser, db: DBSession) -> dict:
    """导入 BestBlogs 文档推荐的编程精选聚合 RSS 白名单。"""
    return upsert_bestblogs_whitelist(db)


class RunIn(BaseModel):
    fetch: bool = True
    for_me: bool = True  # 学生端固定为自己推送
    agent_id: int | None = None
    lang: str = "zh"  # zh | en | any
    resource_type: str = "all"  # all | article | podcast | video | twitter
    limit: int = Field(default=3, ge=1, le=20)


@router.get("/weak-points")
def my_weak_points(user: CurrentUser, db: DBSession) -> dict:
    """学生可见：汇总所有课程考核报告中的薄弱点。"""
    if user.role != "student":
        raise HTTPException(403, "仅学生可查看个人薄弱点")
    from ..services.weakness_service import resolve_student_weak_targets

    targets = resolve_student_weak_targets(db, user, all_courses=True)
    return {
        "items": [
            {
                "kp_name": t["kp_name"],
                "weight": t["weight"],
                "chapter_id": t.get("chapter_id"),
            }
            for t in targets
        ]
    }


@router.post("/run", dependencies=[Depends(require_role("student"))])
def run_push(payload: RunIn, user: CurrentUser, db: DBSession) -> dict:
    """学生手动刷新：按语言与条数，基于全课程考核报告薄弱点生成推送。"""
    if payload.resource_type not in ("all", "article", "podcast", "video", "twitter"):
        raise HTTPException(400, "不支持的资源类型")
    return push_for_user_now(
        db,
        user,
        agent_id=payload.agent_id,
        fetch=payload.fetch,
        lang=payload.lang,
        limit=payload.limit,
        resource_type=payload.resource_type,
    )


@router.post("/fetch", dependencies=[Depends(require_role("admin"))])
def fetch_only(_u: CurrentUser, db: DBSession) -> dict:
    """管理员仅可拉取 RSS 入库，不可触发对学生推送。"""
    return fetch_all_sources(db)


@router.delete("/admin/records", dependencies=[Depends(require_role("admin"))])
def clear_all_records(_u: CurrentUser, db: DBSession) -> dict:
    """清空全部推送记录（文章库与源保留）。"""
    from sqlalchemy import delete

    n = db.scalar(select(func.count()).select_from(KnowledgePush)) or 0
    db.execute(delete(KnowledgePush))
    db.commit()
    return {"ok": True, "deleted": n}
