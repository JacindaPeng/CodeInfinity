"""白名单 RSS / 可选搜索 API 拉取候选文章（不做站点 HTML 重爬）。"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import KnowledgeArticle, KnowledgeSource

logger = logging.getLogger(__name__)

RESOURCE_TYPES = ("article", "podcast", "video", "twitter")
RESOURCE_TYPE_NAMES = {
    "article": "文章",
    "podcast": "播客",
    "video": "视频",
    "twitter": "推文",
}


def _bestblogs_presets() -> tuple[dict, ...]:
    presets: list[dict] = []
    for lang, language, base in (
        ("中文", "zh", "https://www.bestblogs.dev/zh"),
        ("English", "en", "https://www.bestblogs.dev/en"),
    ):
        for resource_type in RESOURCE_TYPES:
            label = RESOURCE_TYPE_NAMES[resource_type]
            if resource_type == "article":
                filters = (
                    "&timeFilter=1m&minScore=85&featured=y"
                    "&category=programming"
                )
            else:
                # 音视频/推文数量较少，放宽到近三月 75 分，仍保留质量门槛。
                filters = "&timeFilter=3m&minScore=75"
            presets.append({
                "name": f"BestBlogs {lang}{label}精选",
                "base_url": base,
                "rss_url": (
                    f"{base}/feeds/rss?language={language}"
                    f"&type={resource_type}{filters}"
                ),
                "tags": (
                    f"bestblogs,{resource_type},{language},"
                    + ("featured,score85,programming" if resource_type == "article"
                       else "score75")
                ),
                "resource_type": resource_type,
            })
    return tuple(presets)


BESTBLOGS_WHITELIST_PRESETS = _bestblogs_presets()

# 菜鸟教程公开课程页。作为教材型白名单直接入库，不爬取页面正文。
RUNOOB_TUTORIALS = (
    ("C 语言教程", "https://www.runoob.com/cprogramming/c-tutorial.html",
     "C语言入门、发展历程、程序结构、编译运行", ["C语言", "发展历程", "完整程序", "编写到运行"]),
    ("C 环境设置", "https://www.runoob.com/cprogramming/c-environment-setup.html",
     "C语言开发环境、编译器与集成开发环境配置", ["集成开发环境", "开发环境", "编译", "运行"]),
    ("C 程序结构", "https://www.runoob.com/cprogramming/c-program-structure.html",
     "main函数、头文件、程序入口与完整C程序结构", ["main函数", "stdio.h", "头文件", "程序结构", "完整程序"]),
    ("C 数据类型", "https://www.runoob.com/cprogramming/c-data-types.html",
     "整型、浮点型、字符型与类型转换", ["数据类型", "浮点数", "整型", "字符"]),
    ("C 运算符", "https://www.runoob.com/cprogramming/c-operators.html",
     "关系运算符、表达式、优先级与结合性", ["关系表达式", "连续比较", "结合性", "运算符"]),
    ("C 循环", "https://www.runoob.com/cprogramming/c-loops.html",
     "for、while、do while 循环语句", ["循环", "for", "while"]),
    ("C 数组", "https://www.runoob.com/cprogramming/c-arrays.html",
     "一维数组、二维数组与数组操作", ["数组", "二维数组"]),
    ("C 函数", "https://www.runoob.com/cprogramming/c-functions.html",
     "函数定义、声明、参数与调用", ["函数", "函数调用"]),
    ("C 指针", "https://www.runoob.com/cprogramming/c-pointers.html",
     "指针、地址、数组指针与内存访问", ["指针", "地址", "内存"]),
    ("C 结构体", "https://www.runoob.com/cprogramming/c-structures.html",
     "结构体定义、成员访问与结构体数组", ["结构体"]),
    ("C 预处理器", "https://www.runoob.com/cprogramming/c-preprocessors.html",
     "预处理指令、宏与标准头文件", ["预处理", "宏", "头文件"]),
    ("Python3 教程", "https://www.runoob.com/python3/python3-tutorial.html",
     "Python3 基础语法与程序设计教程", ["Python", "python"]),
    ("C++ 教程", "https://www.runoob.com/cplusplus/cpp-tutorial.html",
     "C++ 基础语法、类、对象与标准库", ["C++", "cpp", "类", "对象"]),
    ("Java 教程", "https://www.runoob.com/java/java-tutorial.html",
     "Java 基础语法、面向对象与 JVM", ["Java", "java", "JVM", "面向对象"]),
    ("SQL 教程", "https://www.runoob.com/sql/sql-tutorial.html",
     "SQL 查询、表、连接与数据库基础", ["SQL", "sql", "数据库", "JOIN"]),
    ("数据结构与算法", "https://www.runoob.com/data-structures/data-structures-tutorial.html",
     "常见数据结构、算法与复杂度", ["数据结构", "算法", "复杂度"]),
)


def upsert_bestblogs_whitelist(db: Session) -> dict:
    """导入 BestBlogs 的高质量编程聚合源，重复调用只更新配置。"""
    created = 0
    updated = 0
    for legacy in db.scalars(select(KnowledgeSource)).all():
        if "bestblogs" in (legacy.tags or "").lower():
            legacy.enabled = False
    for preset in BESTBLOGS_WHITELIST_PRESETS:
        source = db.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.name == preset["name"],
            )
        )
        if source is None:
            source = db.scalar(
                select(KnowledgeSource).where(
                    KnowledgeSource.rss_url == preset["rss_url"],
                )
            )
        if source is None:
            db.add(KnowledgeSource(**preset, enabled=True))
            created += 1
            continue
        source.name = preset["name"]
        source.base_url = preset["base_url"]
        source.rss_url = preset["rss_url"]
        source.tags = preset["tags"]
        source.resource_type = preset["resource_type"]
        source.enabled = True
        updated += 1
    db.commit()
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "total": len(BESTBLOGS_WHITELIST_PRESETS),
    }


def upsert_runoob_tutorials(db: Session) -> dict:
    """写入菜鸟教程课程页，供薄弱点优先匹配。"""
    source = db.scalar(
        select(KnowledgeSource).where(KnowledgeSource.name == "菜鸟教程")
    )
    if source is None:
        source = KnowledgeSource(
            name="菜鸟教程",
            base_url="https://www.runoob.com/",
            rss_url="",
            enabled=True,
            tags="runoob,tutorial,zh,programming",
            resource_type="article",
        )
        db.add(source)
        db.flush()
    else:
        source.base_url = "https://www.runoob.com/"
        source.enabled = True
        source.tags = "runoob,tutorial,zh,programming"
        source.resource_type = "article"

    created = 0
    updated = 0
    for title, url, summary, keywords in RUNOOB_TUTORIALS:
        article = db.scalar(
            select(KnowledgeArticle).where(KnowledgeArticle.url == url)
        )
        if article is None:
            db.add(KnowledgeArticle(
                source_id=source.id,
                url=url,
                title=title,
                summary=summary,
                keywords_json=keywords,
                resource_type="article",
            ))
            created += 1
            continue
        article.source_id = source.id
        article.title = title
        article.summary = summary
        article.keywords_json = keywords
        article.resource_type = "article"
        updated += 1
    db.commit()
    return {"ok": True, "created": created, "updated": updated, "total": len(RUNOOB_TUTORIALS)}


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _parse_published(entry) -> datetime | None:
    for key in ("published", "updated"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            return parsedate_to_datetime(raw)
        except Exception:
            pass
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).replace(tzinfo=None)
            except Exception:
                pass
    return None


def _extract_keywords(title: str, summary: str) -> list[str]:
    blob = f"{title} {summary}"
    # 中文词块 + 英文单词
    cn = re.findall(r"[\u4e00-\u9fff]{2,12}", blob)
    en = re.findall(r"[A-Za-z][A-Za-z0-9_+#.]{1,24}", blob)
    seen: set[str] = set()
    out: list[str] = []
    for w in cn + [x.lower() for x in en]:
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= 40:
            break
    return out


def upsert_article(
    db: Session,
    *,
    source_id: int,
    url: str,
    title: str,
    summary: str,
    published_at: datetime | None,
    resource_type: str = "article",
) -> KnowledgeArticle | None:
    url = (url or "").strip()
    if not url.startswith("http"):
        return None
    existing = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.url == url))
    title = (title or "").strip()[:512]
    summary = _strip_html(summary)[:2000]
    kws = _extract_keywords(title, summary)
    if existing:
        existing.title = title or existing.title
        existing.summary = summary or existing.summary
        if published_at:
            existing.published_at = published_at
        existing.keywords_json = kws
        existing.resource_type = resource_type
        existing.fetched_at = datetime.utcnow()
        return existing
    art = KnowledgeArticle(
        source_id=source_id,
        url=url,
        title=title or url,
        summary=summary,
        published_at=published_at,
        keywords_json=kws,
        resource_type=resource_type,
    )
    db.add(art)
    return art


_RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CourseAgentKnowledgePush/1.0; "
        "+https://localhost)"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def _download_rss(url: str, *, timeout: float = 12.0, retries: int = 1) -> bytes | None:
    """用 httpx 拉取完整 RSS 正文，避免 urllib IncompleteRead。"""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(timeout, connect=6.0),
                follow_redirects=True,
                headers=_RSS_HEADERS,
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                content = resp.content or b""
                if len(content) < 32:
                    raise ValueError(f"RSS 内容过短 ({len(content)} bytes)")
                return content
        except Exception as e:
            last_err = e
            logger.warning(
                "RSS download attempt %s failed %s: %s",
                attempt + 1, url, e,
            )
    if last_err:
        logger.warning("RSS download gave up %s: %s", url, last_err)
    return None


def fetch_source_rss(db: Session, source: KnowledgeSource) -> int:
    """拉取单个 RSS，返回新增/更新条数。"""
    if not source.enabled or not source.rss_url:
        return 0
    content = _download_rss(source.rss_url)
    if content is None:
        # 回退：让 feedparser 直连再试一次（部分源兼容性更好）
        try:
            parsed = feedparser.parse(source.rss_url)
        except Exception as e:
            logger.warning("RSS parse failed %s: %s", source.rss_url, e)
            return 0
    else:
        try:
            parsed = feedparser.parse(content)
        except Exception as e:
            logger.warning("RSS parse failed %s: %s", source.rss_url, e)
            return 0
    if getattr(parsed, "bozo", False) and not parsed.entries:
        logger.warning(
            "RSS empty/bozo %s: %s",
            source.rss_url,
            getattr(parsed, "bozo_exception", None),
        )
        return 0
    n = 0
    for entry in parsed.entries[:40]:
        link = entry.get("link") or ""
        title = entry.get("title") or ""
        summary = entry.get("summary") or entry.get("description") or ""
        art = upsert_article(
            db,
            source_id=source.id,
            url=link,
            title=title,
            summary=summary,
            published_at=_parse_published(entry),
            resource_type=source.resource_type or "article",
        )
        if art:
            n += 1
    return n


def fetch_all_sources(db: Session, *, soft_fail: bool = True) -> dict:
    """拉取全部启用源。soft_fail=True 时单源失败不中断，保证仍可用本地文库推送。"""
    sources = db.scalars(
        select(KnowledgeSource).where(KnowledgeSource.enabled.is_(True))
    ).all()
    total = 0
    failed = 0
    details = []
    for src in sources:
        try:
            c = fetch_source_rss(db, src)
            total += c
            details.append({"source_id": src.id, "name": src.name, "upserted": c})
        except Exception as e:
            failed += 1
            logger.exception("fetch source %s", src.id)
            details.append({"source_id": src.id, "name": src.name, "error": str(e)})
            if not soft_fail:
                raise
    try:
        db.commit()
    except Exception as e:
        logger.warning("commit after RSS fetch failed: %s", e)
        db.rollback()
    search_n = 0
    if settings.search_api_key:
        try:
            search_n = fetch_via_bing_search(db)
            db.commit()
        except Exception as e:
            logger.warning("Bing search fetch failed: %s", e)
    return {
        "sources": len(sources),
        "upserted": total,
        "failed": failed,
        "search_upserted": search_n,
        "details": details,
    }


def whitelist_domains(db: Session) -> set[str]:
    domains: set[str] = set()
    for src in db.scalars(select(KnowledgeSource).where(KnowledgeSource.enabled.is_(True))).all():
        for raw in (src.base_url, src.rss_url):
            try:
                host = urlparse(raw).netloc.lower()
                if host.startswith("www."):
                    host = host[4:]
                if host:
                    domains.add(host)
            except Exception:
                pass
    return domains


def fetch_via_bing_search(db: Session, queries: list[str] | None = None) -> int:
    """可选：Bing Web Search，结果限制在白名单域名内。"""
    if not settings.search_api_key:
        return 0
    domains = whitelist_domains(db)
    if not domains:
        return 0
    if not queries:
        queries = ["Python 编程入门", "C language pointers", "SQL JOIN 教程"]
    # 用一个通用 source：名称为 Search API
    src = db.scalar(select(KnowledgeSource).where(KnowledgeSource.name == "Search API"))
    if not src:
        src = KnowledgeSource(
            name="Search API",
            base_url="",
            rss_url="https://api.bing.microsoft.com/v7.0/search",
            enabled=True,
            tags="general",
        )
        db.add(src)
        db.flush()

    n = 0
    headers = {"Ocp-Apim-Subscription-Key": settings.search_api_key}
    site_filter = " OR ".join(f"site:{d}" for d in list(domains)[:5])
    with httpx.Client(timeout=20.0) as client:
        for q in queries[:5]:
            try:
                resp = client.get(
                    "https://api.bing.microsoft.com/v7.0/search",
                    headers=headers,
                    params={"q": f"{q} ({site_filter})", "count": 8, "mkt": "zh-CN"},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for item in (data.get("webPages") or {}).get("value") or []:
                    url = item.get("url") or ""
                    host = urlparse(url).netloc.lower().removeprefix("www.")
                    if host not in domains and not any(host.endswith("." + d) for d in domains):
                        continue
                    art = upsert_article(
                        db,
                        source_id=src.id,
                        url=url,
                        title=item.get("name") or "",
                        summary=item.get("snippet") or "",
                        published_at=None,
                    )
                    if art:
                        n += 1
            except Exception as e:
                logger.warning("bing query %s: %s", q, e)
    return n


def score_article_for_kps(article: KnowledgeArticle, kp_names: list[str]) -> tuple[float, list[str]]:
    """文章与知识点关键词打分。"""
    blob = _norm_blob(f"{article.title} {article.summary} {' '.join(article.keywords_json or [])}")
    hit: list[str] = []
    score = 0.0
    for name in kp_names:
        n = _norm_blob(name)
        if len(n) < 2:
            continue
        if n in blob:
            score += 2.0 + min(len(n), 12) * 0.1
            hit.append(name)
        else:
            # 英文/碎片
            parts = re.split(r"[\s/、，,]+", name)
            for p in parts:
                pn = _norm_blob(p)
                if len(pn) >= 3 and pn in blob:
                    score += 1.0
                    hit.append(name)
                    break
    return score, list(dict.fromkeys(hit))


def _norm_blob(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip().lower())
