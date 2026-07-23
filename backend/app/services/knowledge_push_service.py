"""生成学生每日知识推送。"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Agent,
    AgentClass,
    ClassEnrollment,
    Course,
    KnowledgeArticle,
    KnowledgePush,
    KnowledgeSource,
    TeachingClass,
    User,
)
from .knowledge_fetch_service import fetch_all_sources, score_article_for_kps
from .weakness_service import resolve_student_weak_targets

logger = logging.getLogger(__name__)


def _active_agents_for_student(db: Session, user: User) -> list[Agent]:
    """学生可见智能体：班级已绑定优先；否则回退到选课课程下的已上线智能体。"""
    enrollments = list(
        db.scalars(
            select(ClassEnrollment).where(ClassEnrollment.user_id == user.id)
        ).all()
    )
    if not enrollments:
        return []

    class_ids = [e.class_id for e in enrollments]
    course_ids = list({e.course_id for e in enrollments if e.course_id})
    if not course_ids:
        course_ids = list(
            db.scalars(
                select(TeachingClass.course_id).where(
                    TeachingClass.id.in_(class_ids),
                    TeachingClass.course_id.isnot(None),
                )
            ).all()
        )

    agent_ids = list(
        db.scalars(
            select(AgentClass.agent_id).where(AgentClass.class_id.in_(class_ids))
        ).all()
    )
    if agent_ids:
        rows = list(
            db.scalars(
                select(Agent).where(Agent.id.in_(agent_ids), Agent.status == "active")
            ).all()
        )
        if rows:
            return rows

    if not course_ids:
        return []
    return list(
        db.scalars(
            select(Agent)
            .where(Agent.course_id.in_(course_ids), Agent.status == "active")
            .order_by(Agent.id)
        ).all()
    )


def _course_keywords(db: Session, course_id: int | None) -> list[str]:
    if not course_id:
        return ["programming", "编程", "c", "sql"]
    course = db.get(Course, course_id)
    name = (course.name if course else "") or ""
    kws = ["programming", "编程"]
    lower = name.lower()
    if "python" in lower or "Python" in name:
        kws.extend(["python", "pandas", "numpy"])
    elif "c++" in lower or "C++" in name:
        kws.extend(["c++", "qt", "cpp"])
    elif "java" in lower:
        kws.extend(["java", "jvm"])
    elif "数据" in name or "sql" in lower or "数据库" in name:
        kws.extend(["sql", "database", "数据库"])
    else:
        # C 语言等：不要混入 python，避免误标为薄弱点
        kws.extend(["c language", "pointer", "array", "stdio", "C语言"])
    return kws


def _official_weak_names(targets: list[dict]) -> list[str]:
    """考核报告中的完整薄弱点名称（不含碎片）。"""
    return [t["kp_name"] for t in targets if t.get("kp_name")]


def _weak_keyword_set(targets: list[dict]) -> set[str]:
    """仅完整薄弱点名，用于校验展示标签。"""
    return set(_official_weak_names(targets))


def _normalize_kp_display_hits(hits: list[str], targets: list[dict]) -> list[str]:
    """展示用标签：必须是完整薄弱点，否则归为课程延伸阅读。"""
    official = set(_official_weak_names(targets))
    valid = [h for h in hits if h in official]
    if valid:
        return list(dict.fromkeys(valid))[:8]
    return ["课程延伸阅读"]


def _sanitize_false_weak_reasons(
    db: Session, user_id: int, weak_keys: set[str]
) -> int:
    """纠正历史错误：碎片词/误标薄弱点改为课程延伸阅读。"""
    rows = db.scalars(
        select(KnowledgePush).where(
            KnowledgePush.user_id == user_id,
            KnowledgePush.status.in_(("unread", "read")),
        )
    ).all()
    fixed = 0
    for p in rows:
        hits = list(p.kp_names_json or [])
        if hits and all(h in weak_keys for h in hits):
            continue
        if hits in (["延伸阅读"], ["课程延伸阅读"]) or not hits:
            if p.kp_names_json != ["课程延伸阅读"]:
                p.kp_names_json = ["课程延伸阅读"]
                fixed += 1
            continue
        p.kp_names_json = ["课程延伸阅读"]
        fixed += 1
    return fixed


def detect_article_lang(article: KnowledgeArticle) -> str:
    """粗分中文 / 英文：中文字符达到阈值则为 zh，否则 en。"""
    text = f"{article.title or ''}{article.summary or ''}"
    if not text.strip():
        return "en"
    cn = len(re.findall(r"[\u4e00-\u9fff]", text))
    letters = len(re.findall(r"[A-Za-z]", text))
    # 标题里有少量中文即倾向 zh（周刊/博客常见中英混排）
    if cn >= 4 or (cn >= 2 and cn >= letters * 0.2):
        return "zh"
    return "en"


def _filter_articles_by_lang(
    articles: list[KnowledgeArticle], lang: str
) -> list[KnowledgeArticle]:
    lang = (lang or "any").lower()
    if lang in ("", "any", "all"):
        return articles
    if lang not in ("zh", "en", "zh-cn", "zh_cn", "chinese", "english"):
        return articles
    want = "zh" if lang in ("zh", "zh-cn", "zh_cn", "chinese") else "en"
    return [a for a in articles if detect_article_lang(a) == want]


def _match_articles(
    articles: list[KnowledgeArticle],
    targets: list[dict],
    already: set[int],
    *,
    course_keywords: list[str] | None = None,
    fill_unmatched: bool = True,
) -> list[tuple[float, KnowledgeArticle, list[str]]]:
    weak_kp_names = _official_weak_names(targets)
    # 碎片仅用于召回打分，不用于展示标签
    extra: list[str] = []
    for name in list(weak_kp_names):
        if len(name) > 24:
            extra.extend(re.findall(r"[\u4e00-\u9fff]{2,8}", name)[:6])
            extra.extend(re.findall(r"[A-Za-z][A-Za-z0-9_+#.]{2,16}", name)[:4])
    scoring_keywords = list(dict.fromkeys(weak_kp_names + extra + (course_keywords or [])))
    weight_map = {t["kp_name"]: float(t["weight"]) for t in targets}

    scored: list[tuple[float, KnowledgeArticle, list[str]]] = []
    for art in articles:
        if art.id in already:
            continue
        score, _ = score_article_for_kps(art, scoring_keywords)
        if score <= 0:
            continue
        _, weak_hits = score_article_for_kps(art, weak_kp_names)
        display_hits = _normalize_kp_display_hits(weak_hits, targets)
        bonus = sum(weight_map.get(h, 0) for h in weak_hits)
        scored.append((score + bonus * 0.5, art, display_hits))
    scored.sort(key=lambda x: -x[0])
    if scored:
        return scored

    soft_keys = course_keywords or ["programming", "编程", "c language", "sql"]
    # 中文延伸阅读常见词，避免只靠英文 soft key 导致中文池匹配为空
    soft_keys = list(dict.fromkeys(soft_keys + [
        "编程", "程序", "语言", "指针", "数组", "函数", "算法", "数据",
        "开发", "教程", "学习", "计算机", "软件", "代码", "技术",
    ]))
    for art in articles:
        if art.id in already:
            continue
        blob = f"{art.title} {art.summary}".lower()
        if any(k.lower() in blob for k in soft_keys):
            scored.append((0.3, art, ["课程延伸阅读"]))
    scored.sort(key=lambda x: -x[0])
    if scored or not fill_unmatched:
        return scored

    # 语言已过滤后仍无关键词命中：按时间回填，保证「刷新中文/英文」可用
    leftovers: list[tuple[float, KnowledgeArticle, list[str]]] = []
    for art in articles:
        if art.id in already:
            continue
        leftovers.append((0.1, art, ["课程延伸阅读"]))
    leftovers.sort(
        key=lambda x: (
            x[1].published_at or x[1].fetched_at or datetime.min,
        ),
        reverse=True,
    )
    return leftovers


def _match_runoob_tutorials(
    articles: list[KnowledgeArticle],
    targets: list[dict],
    already: set[int],
) -> list[tuple[float, KnowledgeArticle, list[str]]]:
    """按薄弱点中的关键短语匹配菜鸟教程；命中项优先于课外内容。"""
    scored: list[tuple[float, KnowledgeArticle, list[str]]] = []
    for art in articles:
        if art.id in already or not art.source or art.source.name != "菜鸟教程":
            continue
        keywords = [
            str(k).strip().lower()
            for k in (art.keywords_json or [])
            if str(k).strip()
        ]
        hits: list[str] = []
        score = 0.0
        for target in targets:
            name = str(target.get("kp_name") or "")
            lower = name.lower()
            matched = [k for k in keywords if k in lower or lower in k]
            if not matched:
                continue
            hits.append(name)
            score += 20.0 + float(target.get("weight") or 0) + max(
                len(k) for k in matched
            ) * 0.2
        if hits:
            scored.append((score, art, list(dict.fromkeys(hits))))
    scored.sort(key=lambda row: -row[0])
    return scored


def _eligible_article_ids(db: Session, user_id: int) -> set[int]:
    """已占用文章：未读/已读仍占用；已忽略的可再次推荐。"""
    return set(
        db.scalars(
            select(KnowledgePush.article_id).where(
                KnowledgePush.user_id == user_id,
                KnowledgePush.status.in_(("unread", "read")),
            )
        ).all()
    )


def _revive_or_create_push(
    db: Session,
    *,
    user_id: int,
    agent_id: int | None,
    course_id: int | None,
    art: KnowledgeArticle,
    reason: str,
    hits: list[str],
) -> KnowledgePush | None:
    """新建推送；若同文曾被忽略则复活为未读。"""
    existing = db.scalar(
        select(KnowledgePush).where(
            KnowledgePush.user_id == user_id,
            KnowledgePush.article_id == art.id,
        )
    )
    if existing:
        if existing.status != "dismissed":
            return None
        existing.status = "unread"
        existing.reason = reason
        existing.kp_names_json = hits[:8]
        existing.agent_id = agent_id
        existing.course_id = course_id
        existing.pushed_at = datetime.utcnow()
        existing.read_at = None
        return existing

    push = KnowledgePush(
        user_id=user_id,
        agent_id=agent_id,
        course_id=course_id,
        article_id=art.id,
        reason=reason,
        kp_names_json=hits[:8],
        status="unread",
    )
    db.add(push)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        return None
    return push


def _meta_from_targets(
    db: Session, targets: list[dict], fallback_agent: Agent | None
) -> tuple[int | None, int | None]:
    """用薄弱点所属章节推断 course/agent；否则用指定智能体。"""
    from ..models import Chapter

    for t in targets:
        ch_id = t.get("chapter_id")
        if not ch_id:
            continue
        ch = db.get(Chapter, ch_id)
        if not ch:
            continue
        course_id = ch.course_id
        agent_id = ch.agent_id
        if agent_id is None and course_id is not None:
            ag = db.scalar(
                select(Agent)
                .where(Agent.course_id == course_id, Agent.status == "active")
                .order_by(Agent.id)
            )
            agent_id = ag.id if ag else None
        return agent_id, course_id
    if fallback_agent:
        return fallback_agent.id, fallback_agent.course_id
    return None, None


def push_for_student(
    db: Session,
    user: User,
    *,
    agent: Agent | None = None,
    limit: int | None = None,
    lang: str = "any",
    resource_type: str = "all",
) -> list[KnowledgePush]:
    """薄弱点优先匹配菜鸟教程，再从分类白名单补充课外内容。"""
    limit = limit if limit is not None else settings.knowledge_push_limit
    limit = max(1, min(int(limit), 20))
    resource_type = (resource_type or "all").lower()
    if resource_type not in ("all", "article", "podcast", "video", "twitter"):
        resource_type = "all"

    created: list[KnowledgePush] = []
    already = _eligible_article_ids(db, user.id)

    recent_cutoff = datetime.utcnow() - timedelta(days=90)
    articles = list(
        db.scalars(
            select(KnowledgeArticle)
            .join(KnowledgeSource)
            .where(
                KnowledgeSource.enabled.is_(True),
                (KnowledgeArticle.published_at.is_(None))
                | (KnowledgeArticle.published_at >= recent_cutoff)
            )
            .order_by(KnowledgeArticle.fetched_at.desc())
            .limit(500)
        ).all()
    )
    if not articles:
        articles = list(
            db.scalars(
                select(KnowledgeArticle)
                .join(KnowledgeSource)
                .where(KnowledgeSource.enabled.is_(True))
                .order_by(KnowledgeArticle.id.desc())
                .limit(300)
            ).all()
        )
    articles = _filter_articles_by_lang(articles, lang)
    if resource_type != "all":
        articles = [
            a for a in articles if (a.resource_type or "article") == resource_type
        ]

    # 薄弱点：始终汇总所有课程报告
    targets = resolve_student_weak_targets(
        db, user, course_id=None, agent_id=None, all_courses=True
    )
    if not targets:
        targets = [{"chapter_id": None, "kp_name": "编程", "weight": 1.0}]

    weak_keys = set(_official_weak_names(targets))
    if _sanitize_false_weak_reasons(db, user.id, weak_keys):
        db.flush()
        already = _eligible_article_ids(db, user.id)

    # 合并学生各课程关键词，提高跨课匹配
    course_ids: set[int] = set()
    for ag in _active_agents_for_student(db, user):
        if ag.course_id:
            course_ids.add(ag.course_id)
    if agent and agent.course_id:
        course_ids.add(agent.course_id)
    course_keywords: list[str] = []
    if course_ids:
        for cid in course_ids:
            course_keywords.extend(_course_keywords(db, cid))
    else:
        course_keywords.extend(_course_keywords(db, None))
    course_keywords = list(dict.fromkeys(course_keywords))

    runoob_scored = (
        _match_runoob_tutorials(articles, targets, already)
        if resource_type in ("all", "article")
        else []
    )
    external_articles = [
        a for a in articles if not a.source or a.source.name != "菜鸟教程"
    ]
    scored = runoob_scored + _match_articles(
        external_articles, targets, already,
        course_keywords=course_keywords, fill_unmatched=True,
    )

    agent_id, course_id = _meta_from_targets(db, targets, agent)
    for _score, art, hits in scored:
        if len(created) >= limit:
            break
        if art.id in already:
            continue
        hits = _normalize_kp_display_hits(hits, targets)
        if hits == ["课程延伸阅读"]:
            reason = "结合你的多课程学习情况推荐"
        elif art.source and art.source.name == "菜鸟教程":
            reason = f"根据薄弱点优先推荐菜鸟教程：{'、'.join(hits[:4])}"
        else:
            reason = f"根据你的考核报告薄弱点推荐：{'、'.join(hits[:4])}"
        push = _revive_or_create_push(
            db,
            user_id=user.id,
            agent_id=agent_id,
            course_id=course_id,
            art=art,
            reason=reason,
            hits=hits,
        )
        if not push:
            continue
        already.add(art.id)
        created.append(push)

    return created


def run_daily_knowledge_push(
    db: Session,
    *,
    fetch: bool = True,
    student_ids: list[int] | None = None,
    agent_id: int | None = None,
    lang: str = "any",
    limit: int | None = None,
    resource_type: str = "all",
) -> dict:
    """拉取 + 为学生生成推送。student_ids 为空列表时不推；None 表示全体学生。"""
    fetch_result = fetch_all_sources(db) if fetch else {"skipped": True}
    q = select(User).where(User.role == "student")
    if student_ids is not None:
        if not student_ids:
            return {
                "ok": True,
                "fetch": fetch_result,
                "students": 0,
                "pushes_created": 0,
            }
        q = q.where(User.id.in_(student_ids))
    students = db.scalars(q).all()
    agent = db.get(Agent, agent_id) if agent_id else None
    total_pushes = 0
    student_count = 0
    for stu in students:
        student_count += 1
        created = push_for_student(
            db, stu, agent=agent, lang=lang, limit=limit,
            resource_type=resource_type,
        )
        total_pushes += len(created)
    db.commit()
    return {
        "ok": True,
        "fetch": fetch_result,
        "students": student_count,
        "pushes_created": total_pushes,
    }


def push_for_user_now(
    db: Session,
    user: User,
    *,
    agent_id: int | None = None,
    fetch: bool = True,
    lang: str = "any",
    limit: int | None = None,
    resource_type: str = "all",
) -> dict:
    """先用本地文库快速生成推送；外网 RSS 放到后台拉取，避免刷新卡住。"""
    import threading

    from ..database import SessionLocal

    agent = db.get(Agent, agent_id) if agent_id else None
    want = limit if limit is not None else settings.knowledge_push_limit
    want = max(1, min(int(want), 20))

    created = push_for_student(
        db, user, agent=agent, lang=lang, limit=want,
        resource_type=resource_type,
    )
    if not created:
        created = _push_relaxing_already(
            db, user, agent=agent, lang=lang, limit=want,
            resource_type=resource_type,
        )

    fetch_result: dict = {"skipped": True}
    if fetch:
        def _bg_fetch() -> None:
            bg = SessionLocal()
            try:
                result = fetch_all_sources(bg, soft_fail=True)
                logger.info("background knowledge fetch: %s", {
                    "upserted": result.get("upserted"),
                    "failed": result.get("failed"),
                    "sources": result.get("sources"),
                })
            except Exception as e:
                logger.warning("background knowledge fetch failed: %s", e)
            finally:
                bg.close()

        threading.Thread(target=_bg_fetch, daemon=True).start()
        fetch_result = {"started_background": True}

    weak = resolve_student_weak_targets(db, user, all_courses=True)[:10]
    db.commit()
    return {
        "ok": True,
        "fetch": fetch_result,
        "pushes_created": len(created),
        "push_ids": [p.id for p in created],
        "weak_points": [t["kp_name"] for t in weak],
        "lang": lang,
        "resource_type": resource_type,
        "limit": want,
    }


def _push_relaxing_already(
    db: Session,
    user: User,
    *,
    agent: Agent | None,
    lang: str,
    limit: int | None,
    resource_type: str,
) -> list[KnowledgePush]:
    """当未读/已读占满文库时：仅把「已读」文复活为新推送（未读不重复）。"""
    limit = limit if limit is not None else settings.knowledge_push_limit
    limit = max(1, min(int(limit), 20))
    unread_ids = set(
        db.scalars(
            select(KnowledgePush.article_id).where(
                KnowledgePush.user_id == user.id,
                KnowledgePush.status == "unread",
            )
        ).all()
    )
    read_rows = list(
        db.scalars(
            select(KnowledgePush)
            .where(
                KnowledgePush.user_id == user.id,
                KnowledgePush.status == "read",
            )
            .order_by(KnowledgePush.pushed_at.asc())
            .limit(80)
        ).all()
    )
    if not read_rows:
        return []

    articles = list(
        db.scalars(
            select(KnowledgeArticle)
            .join(KnowledgeSource)
            .where(
                KnowledgeSource.enabled.is_(True),
                KnowledgeArticle.id.in_([p.article_id for p in read_rows]),
            )
        ).all()
    )
    articles = _filter_articles_by_lang(articles, lang)
    if resource_type != "all":
        articles = [
            a for a in articles if (a.resource_type or "article") == resource_type
        ]
    art_by_id = {a.id: a for a in articles}
    created: list[KnowledgePush] = []
    targets = resolve_student_weak_targets(db, user, all_courses=True)
    agent_id, course_id = _meta_from_targets(db, targets, agent)
    for p in read_rows:
        if len(created) >= limit:
            break
        if p.article_id in unread_ids:
            continue
        art = art_by_id.get(p.article_id)
        if not art:
            continue
        # 复活为未读视为新一轮推荐
        p.status = "unread"
        p.reason = "再次推荐：精选延伸阅读"
        p.pushed_at = datetime.utcnow()
        p.read_at = None
        if agent_id is not None:
            p.agent_id = agent_id
        if course_id is not None:
            p.course_id = course_id
        created.append(p)
        unread_ids.add(p.article_id)
    return created

