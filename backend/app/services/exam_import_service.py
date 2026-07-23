"""往年考卷导入：文本提取、拆题、答案配对/生成、章节知识点归类、核实后入库。"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import (
    Chapter,
    ExamImportFile,
    ExamImportJob,
    KnowledgePoint,
    QuestionBank,
    QuestionCandidate,
    User,
)
from .agent_access import (
    is_adopted_snapshot,
    resolve_agent_for_exam,
    resolve_bank_class_ids,
)
from .chapter_sync import (
    agent_scoped_chapter_condition,
    requires_agent_scoped_chapters,
)
from .chat_file_service import extract_file_text
from .exam_service import _run_sync
from .llm_provider import get_provider

ALLOWED_EXTS = {".pdf", ".doc", ".docx"}
STANDARD_TYPES = ["选择题", "判断题", "填空题", "简答题"]
_MAX_PAPER_CHARS = 120_000
_BATCH_SIZE = 12

_QNUM_RE = re.compile(
    r"(?:^|\n)\s*(?:"
    r"(?:第\s*)?(?P<num>\d{1,3})\s*[.?、．)]|"
    r"(?P<cn>[一二三四五六七八九十]+)\s*[、.]"
    r")\s*",
)
_SECTION_RE = re.compile(
    r"(?:^|\n)\s*[一二三四五六七八九十]+、\s*"
    r"(?:选择题|判断题|填空题|简答题|编程题|程序题|应用题|综合题|[^\n]{0,20}题)",
)


def stem_hash(stem: str) -> str:
    norm = re.sub(r"\s+", "", (stem or "").strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


def _parse_json_any(raw: str):
    text = (raw or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("[", "]"), ("{", "}")):
        try:
            s = text[text.index(open_c) : text.rindex(close_c) + 1]
            return json.loads(s)
        except Exception:
            continue
    return None


def _llm_json(prompt: str):
    provider = get_provider()
    raw = _run_sync(provider, [{"role": "user", "content": prompt}])
    return _parse_json_any(raw)


def extract_paper_text(file_path: str, filename: str) -> str:
    """提取试卷文本；扫描件无文字时抛出说明性错误。"""
    try:
        _, text, _ = extract_file_text(file_path, filename)
    except Exception as e:
        msg = str(getattr(e, "detail", None) or e)
        if "未能从文件" in msg or "提取到文本" in msg:
            raise ValueError(
                f"未能从「{filename}」提取到文本。若为扫描版 PDF/图片，"
                "当前版本暂不支持 OCR，请上传可复制文本的 PDF 或 Word。"
            ) from e
        raise ValueError(msg) from e
    text = (text or "").strip()
    if not text:
        raise ValueError(
            f"「{filename}」未提取到文字内容（可能是扫描件）。"
            "请上传可复制文本的 PDF / DOC / DOCX。"
        )
    if len(text) > _MAX_PAPER_CHARS:
        text = text[:_MAX_PAPER_CHARS] + "\n\n…（内容过长，已截断）"
    return text


def _guess_type_from_section(section_title: str) -> str:
    t = section_title or ""
    if "选择" in t:
        return "选择题"
    if "判断" in t:
        return "判断题"
    if "填空" in t:
        return "填空题"
    if "编程" in t or "程序" in t:
        return "简答题"
    if "简答" in t or "问答" in t or "应用" in t or "综合" in t:
        return "简答题"
    return "简答题"


def _rule_split_questions(paper_text: str) -> list[dict]:
    """按题号粗拆；失败返回空，交由 LLM。"""
    sections: list[tuple[int, str, str]] = []
    for m in _SECTION_RE.finditer(paper_text):
        sections.append((m.start(), m.group(0).strip(), ""))
    if not sections:
        sections = [(0, "", "")]
    else:
        # 补全文起始
        if sections[0][0] > 0:
            sections.insert(0, (0, "", ""))

    out: list[dict] = []
    for i, (start, title, _) in enumerate(sections):
        end = sections[i + 1][0] if i + 1 < len(sections) else len(paper_text)
        block = paper_text[start:end]
        default_type = _guess_type_from_section(title)
        matches = list(_QNUM_RE.finditer(block))
        if not matches:
            continue
        for j, m in enumerate(matches):
            q_start = m.end()
            q_end = matches[j + 1].start() if j + 1 < len(matches) else len(block)
            body = block[q_start:q_end].strip()
            if len(body) < 4:
                continue
            num = m.group("num") or m.group("cn") or str(len(out) + 1)
            options: list[str] = []
            qtype = default_type
            opt_matches = list(
                re.finditer(r"(?:^|\n)\s*([A-D])[.．、)]\s*([^\n]+)", body)
            )
            if len(opt_matches) >= 2:
                qtype = "选择题"
                stem = body[: opt_matches[0].start()].strip()
                options = [f"{om.group(1)}. {om.group(2).strip()}" for om in opt_matches]
            else:
                stem = body
                if qtype == "判断题" or re.search(r"(对|错|正确|错误)", body[:80]):
                    if "判断" in title or re.search(r"[（(]\s*(正确|错误|对|错)", body):
                        qtype = "判断题"
                        options = ["对", "错"]
            out.append({
                "original_number": str(num),
                "type": qtype,
                "stem": stem,
                "options": options,
                "answer": "",
                "analysis": "",
                "source_page": None,
            })
    return out


def _llm_split_questions(paper_text: str) -> list[dict]:
    """LLM 拆题；对长文本分块。"""
    chunks: list[str] = []
    if len(paper_text) <= 14000:
        chunks = [paper_text]
    else:
        step = 12000
        for i in range(0, len(paper_text), step):
            chunks.append(paper_text[i : i + step + 800])

    all_items: list[dict] = []
    for idx, chunk in enumerate(chunks):
        prompt = f"""你是试卷结构化助手。请从以下考卷文本中拆出全部题目。
这是第 {idx + 1}/{len(chunks)} 段文本。

要求：
1. 严格输出 JSON 数组，每项字段：
   original_number, type, stem, options, answer, analysis, source_page
2. type 只能是：选择题、判断题、填空题、简答题；若试卷有其它题型名称也映射到最接近的一类，
   确实无法映射时可用原题型名（不超过 8 字）
3. 选择题 options 为 ["A. ...","B. ...",...]；判断题 options 为 ["对","错"]；其它可为空数组
4. 若本段不含完整题目或只是答案页，输出 []
5. 不要输出 markdown 代码块或解释

考卷文本：
{chunk}
"""
        data = _llm_json(prompt)
        if not isinstance(data, list):
            continue
        for it in data:
            if not isinstance(it, dict):
                continue
            stem = str(it.get("stem") or "").strip()
            if len(stem) < 4:
                continue
            qtype = str(it.get("type") or "简答题").strip() or "简答题"
            if len(qtype) > 16:
                qtype = "简答题"
            options = it.get("options") or []
            if not isinstance(options, list):
                options = []
            options = [str(o) for o in options if str(o).strip()]
            page = it.get("source_page")
            try:
                page = int(page) if page is not None else None
            except (TypeError, ValueError):
                page = None
            all_items.append({
                "original_number": str(it.get("original_number") or "").strip(),
                "type": qtype,
                "stem": stem,
                "options": options,
                "answer": str(it.get("answer") or "").strip(),
                "analysis": str(it.get("analysis") or "").strip(),
                "source_page": page,
            })
    # 去重
    seen: set[str] = set()
    uniq: list[dict] = []
    for it in all_items:
        h = stem_hash(it["stem"])
        if h in seen:
            continue
        seen.add(h)
        uniq.append(it)
    return uniq


def split_questions(paper_text: str) -> list[dict]:
    ruled = _rule_split_questions(paper_text)
    if len(ruled) >= 3:
        # 规则拆得较好时仍用 LLM 补答案字段可能为空；优先规则结果
        llm_items = []
        try:
            llm_items = _llm_split_questions(paper_text)
        except Exception:
            llm_items = []
        if len(llm_items) > len(ruled) * 1.3:
            return llm_items
        # 用 LLM 结果按题干相似度补全答案
        if llm_items:
            by_hash = {stem_hash(x["stem"]): x for x in llm_items}
            for r in ruled:
                hit = by_hash.get(stem_hash(r["stem"]))
                if hit:
                    if not r.get("answer") and hit.get("answer"):
                        r["answer"] = hit["answer"]
                    if not r.get("analysis") and hit.get("analysis"):
                        r["analysis"] = hit["analysis"]
                    if hit.get("options") and not r.get("options"):
                        r["options"] = hit["options"]
                    if hit.get("type"):
                        r["type"] = hit["type"]
        return ruled
    return _llm_split_questions(paper_text)


def _llm_pair_answers(questions: list[dict], answer_text: str) -> list[dict]:
    if not answer_text.strip():
        return questions
    # 分批匹配
    result = [dict(q) for q in questions]
    for i in range(0, len(result), _BATCH_SIZE):
        batch = result[i : i + _BATCH_SIZE]
        slim = [
            {
                "idx": i + j,
                "original_number": q.get("original_number"),
                "type": q.get("type"),
                "stem": (q.get("stem") or "")[:300],
            }
            for j, q in enumerate(batch)
        ]
        prompt = f"""根据答案文本，为下列题目匹配答案与解析。
输出 JSON 数组，每项：{{"idx":数字,"answer":"...","analysis":"..."}}
找不到则 answer 置空字符串。只输出 JSON。

题目：
{json.dumps(slim, ensure_ascii=False)}

答案文本：
{answer_text[:20000]}
"""
        data = _llm_json(prompt)
        if not isinstance(data, list):
            continue
        for it in data:
            if not isinstance(it, dict):
                continue
            try:
                idx = int(it["idx"])
            except Exception:
                continue
            if 0 <= idx < len(result):
                ans = str(it.get("answer") or "").strip()
                ana = str(it.get("analysis") or "").strip()
                if ans:
                    result[idx]["answer"] = ans
                if ana:
                    result[idx]["analysis"] = ana
    return result


def _llm_generate_missing_answers(questions: list[dict], course_hint: str = "") -> list[dict]:
    result = [dict(q) for q in questions]
    need_idx = [i for i, q in enumerate(result) if not (q.get("answer") or "").strip()]
    for start in range(0, len(need_idx), _BATCH_SIZE):
        idxs = need_idx[start : start + _BATCH_SIZE]
        slim = [
            {
                "idx": i,
                "type": result[i].get("type"),
                "stem": result[i].get("stem"),
                "options": result[i].get("options") or [],
            }
            for i in idxs
        ]
        prompt = f"""你是编程课教师。请为下列考题生成参考答案与简要解析。
课程提示：{course_hint or "编程课程"}
输出 JSON 数组：{{"idx":数字,"answer":"...","analysis":"..."}}
选择题 answer 填选项字母；判断题填「对」或「错」。只输出 JSON。

题目：
{json.dumps(slim, ensure_ascii=False)}
"""
        data = _llm_json(prompt)
        if not isinstance(data, list):
            continue
        for it in data:
            if not isinstance(it, dict):
                continue
            try:
                idx = int(it["idx"])
            except Exception:
                continue
            if 0 <= idx < len(result):
                ans = str(it.get("answer") or "").strip()
                ana = str(it.get("analysis") or "").strip()
                if ans:
                    result[idx]["answer"] = ans
                    result[idx]["_answer_source"] = "ai"
                if ana:
                    result[idx]["analysis"] = ana
    return result


def _list_chapters(db: Session, course_id: int, agent_id: int | None) -> list[Chapter]:
    q = select(Chapter).where(Chapter.course_id == course_id)
    if requires_agent_scoped_chapters(db, course_id, agent_id):
        q = q.where(agent_scoped_chapter_condition(agent_id))
    q = q.order_by(Chapter.order_idx, Chapter.id)
    return list(db.scalars(q).all())


def _list_kps_for_classes(
    db: Session,
    chapter_ids: list[int],
    class_ids: list[int],
    agent,
) -> list[KnowledgePoint]:
    if not chapter_ids or not class_ids:
        return []
    kp_q = select(KnowledgePoint).where(KnowledgePoint.chapter_id.in_(chapter_ids))
    if agent and is_adopted_snapshot(agent):
        kp_q = kp_q.where(or_(
            KnowledgePoint.agent_id == agent.id,
            KnowledgePoint.class_id.in_(class_ids),
        ))
    else:
        kp_q = kp_q.where(KnowledgePoint.class_id.in_(class_ids))
    return list(db.scalars(kp_q).all())


def _classify_batch(
    questions: list[dict],
    chapters: list[Chapter],
    kps: list[KnowledgePoint],
) -> list[dict]:
    ch_map = {c.id: c.title for c in chapters}
    kp_info = [
        {"id": k.id, "name": k.name, "chapter_id": k.chapter_id}
        for k in kps
    ]
    ch_info = [{"id": c.id, "title": c.title} for c in chapters]
    result = [dict(q) for q in questions]
    if not chapters:
        return result

    for start in range(0, len(result), _BATCH_SIZE):
        batch = result[start : start + _BATCH_SIZE]
        slim = [
            {
                "idx": start + j,
                "type": q.get("type"),
                "stem": (q.get("stem") or "")[:400],
            }
            for j, q in enumerate(batch)
        ]
        prompt = f"""请为下列考题归类章节与知识点。
可选章节（必须从中选 chapter_id，可额外给 extra_chapter_ids）：
{json.dumps(ch_info, ensure_ascii=False)}

已有知识点（优先匹配 kp_id；没有则给 new_kp_name，并指明所属 chapter_id）：
{json.dumps(kp_info[:200], ensure_ascii=False)}

输出 JSON 数组，每项：
{{
  "idx": 数字,
  "chapter_id": 数字,
  "extra_chapter_ids": [数字...],
  "kp_id": 数字或null,
  "new_kp_name": "若需新建则填写，否则空",
  "extra_kp_names": ["附加知识点名"],
  "confidence": 0到1,
  "note": "一句归类理由"
}}
只输出 JSON。

题目：
{json.dumps(slim, ensure_ascii=False)}
"""
        data = _llm_json(prompt)
        if not isinstance(data, list):
            # 降级：全部挂到第一章
            for j, q in enumerate(batch):
                q["chapter_id"] = chapters[0].id
                q["extra_chapter_ids"] = []
                q["kp_id"] = None
                q["new_kp_name"] = ""
                q["extra_kp_names"] = []
                q["confidence"] = 0.3
                q["classification_note"] = "自动归类失败，已默认首章，请教师核实"
            continue
        by_idx = {}
        for it in data:
            if isinstance(it, dict) and "idx" in it:
                try:
                    by_idx[int(it["idx"])] = it
                except Exception:
                    pass
        for j, q in enumerate(batch):
            idx = start + j
            it = by_idx.get(idx, {})
            cid = it.get("chapter_id")
            try:
                cid = int(cid) if cid is not None else chapters[0].id
            except (TypeError, ValueError):
                cid = chapters[0].id
            if cid not in ch_map:
                cid = chapters[0].id
            extras = it.get("extra_chapter_ids") or []
            if not isinstance(extras, list):
                extras = []
            extra_ids = []
            for e in extras:
                try:
                    eid = int(e)
                except (TypeError, ValueError):
                    continue
                if eid in ch_map and eid != cid:
                    extra_ids.append(eid)
            kp_id = it.get("kp_id")
            try:
                kp_id = int(kp_id) if kp_id is not None else None
            except (TypeError, ValueError):
                kp_id = None
            if kp_id is not None and not any(k.id == kp_id for k in kps):
                kp_id = None
            new_name = str(it.get("new_kp_name") or "").strip()[:64]
            if kp_id:
                new_name = ""
            extra_kps = it.get("extra_kp_names") or []
            if not isinstance(extra_kps, list):
                extra_kps = []
            extra_kps = [str(x).strip()[:64] for x in extra_kps if str(x).strip()]
            conf = it.get("confidence")
            try:
                conf = float(conf) if conf is not None else 0.6
            except (TypeError, ValueError):
                conf = 0.6
            q["chapter_id"] = cid
            q["extra_chapter_ids"] = extra_ids
            q["kp_id"] = kp_id
            q["new_kp_name"] = new_name
            q["extra_kp_names"] = extra_kps
            q["confidence"] = max(0.0, min(1.0, conf))
            q["classification_note"] = str(it.get("note") or "")[:500]
    return result


def _update_job(db: Session, job: ExamImportJob, **kwargs) -> None:
    for k, v in kwargs.items():
        setattr(job, k, v)
    job.updated_at = datetime.utcnow()
    db.commit()


def process_import_job(job_id: int) -> None:
    """后台线程入口：解析 → 拆题 → 配答案 → 归类。"""
    db = SessionLocal()
    try:
        job = db.get(ExamImportJob, job_id)
        if not job:
            return
        settings = job.settings_json or {}
        answers_in_paper = bool(settings.get("answers_in_paper"))
        course_hint = str(settings.get("course_name") or "")

        _update_job(db, job, status="parsing", progress=5, error_message="")

        paper_file = next((f for f in job.files if f.role == "paper"), None)
        answer_file = next((f for f in job.files if f.role == "answer"), None)
        if not paper_file:
            _update_job(db, job, status="failed", error_message="缺少试卷文件", progress=100)
            return

        paper_text = extract_paper_text(paper_file.file_path, paper_file.filename)
        paper_file.parse_status = "ok"
        paper_file.extracted_chars = len(paper_text)
        db.commit()

        answer_text = ""
        if answer_file:
            answer_text = extract_paper_text(answer_file.file_path, answer_file.filename)
            answer_file.parse_status = "ok"
            answer_file.extracted_chars = len(answer_text)
            db.commit()
        elif answers_in_paper:
            answer_text = paper_text

        _update_job(db, job, status="parsing", progress=25)
        questions = split_questions(paper_text)
        if not questions:
            _update_job(
                db, job,
                status="failed",
                progress=100,
                error_message="未能从试卷中拆出题目，请检查文件是否为可复制文本版考试卷。",
            )
            return

        _update_job(db, job, status="parsing", progress=45)
        if answer_text:
            questions = _llm_pair_answers(questions, answer_text)
            for q in questions:
                if q.get("answer") and q.get("_answer_source") != "ai":
                    q["_answer_source"] = "paper" if answer_file else "embedded"

        need_ai = [q for q in questions if not (q.get("answer") or "").strip()]
        if need_ai:
            questions = _llm_generate_missing_answers(questions, course_hint=course_hint)

        _update_job(db, job, status="classifying", progress=65)
        chapters = _list_chapters(db, job.course_id, job.agent_id)
        class_ids = list(job.target_class_ids_json or [])
        agent = None
        if job.agent_id or class_ids:
            primary_cid = class_ids[0] if class_ids else None
            agent = resolve_agent_for_exam(
                db,
                db.get(User, job.created_by),
                primary_cid,
                job.course_id,
                job.agent_id,
            )
        bank_class_ids = resolve_bank_class_ids(db, agent, class_ids[0] if class_ids else None)
        if not bank_class_ids:
            bank_class_ids = class_ids
        kps = _list_kps_for_classes(
            db, [c.id for c in chapters], bank_class_ids or class_ids, agent,
        )
        questions = _classify_batch(questions, chapters, kps)

        # 清理旧候选（重试场景）
        for old in list(job.candidates):
            db.delete(old)
        db.flush()

        ai_count = 0
        for q in questions:
            src = q.get("_answer_source") or ("paper" if q.get("answer") else "ai")
            if src == "ai":
                ai_count += 1
            if not q.get("answer"):
                src = "ai"
            cand = QuestionCandidate(
                job_id=job.id,
                original_number=str(q.get("original_number") or "")[:32],
                type=str(q.get("type") or "简答题")[:32],
                stem=str(q.get("stem") or ""),
                options_json=q.get("options") or [],
                answer=str(q.get("answer") or ""),
                analysis=str(q.get("analysis") or ""),
                chapter_id=q.get("chapter_id"),
                extra_chapter_ids_json=q.get("extra_chapter_ids") or [],
                kp_id=q.get("kp_id"),
                new_kp_name=str(q.get("new_kp_name") or "")[:128],
                extra_kp_names_json=q.get("extra_kp_names") or [],
                status="pending",
                answer_source=src,
                confidence=q.get("confidence"),
                source_page=q.get("source_page"),
                classification_note=str(q.get("classification_note") or ""),
                content_hash=stem_hash(str(q.get("stem") or "")),
            )
            db.add(cand)

        job.stats_json = {
            "total": len(questions),
            "ai_answer_count": ai_count,
            "chapter_count": len(chapters),
        }
        job.status = "reviewing"
        job.progress = 100
        job.error_message = ""
        db.commit()
    except Exception as e:
        db.rollback()
        try:
            job = db.get(ExamImportJob, job_id)
            if job:
                job.status = "failed"
                job.progress = 100
                job.error_message = str(e)[:1000]
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def start_import_job_async(job_id: int) -> None:
    t = threading.Thread(target=process_import_job, args=(job_id,), daemon=True)
    t.start()


def candidate_to_dict(c: QuestionCandidate) -> dict:
    return {
        "id": c.id,
        "job_id": c.job_id,
        "original_number": c.original_number,
        "type": c.type,
        "stem": c.stem,
        "options": c.options_json or [],
        "answer": c.answer,
        "analysis": c.analysis,
        "chapter_id": c.chapter_id,
        "extra_chapter_ids": c.extra_chapter_ids_json or [],
        "kp_id": c.kp_id,
        "new_kp_name": c.new_kp_name or "",
        "extra_kp_names": c.extra_kp_names_json or [],
        "status": c.status,
        "answer_source": c.answer_source,
        "confidence": c.confidence,
        "source_page": c.source_page,
        "classification_note": c.classification_note,
        "review_note": c.review_note,
        "content_hash": c.content_hash,
    }


def publish_job(
    db: Session,
    job: ExamImportJob,
    *,
    only_approved: bool = True,
) -> dict:
    """将已通过的候选题事务写入题库；必要时创建知识点。"""
    if job.status not in ("reviewing", "completed"):
        raise ValueError("当前任务状态不可发布，请等待解析完成后再核实入库")

    class_ids = [int(x) for x in (job.target_class_ids_json or [])]
    if not class_ids:
        raise ValueError("未指定目标班级")

    candidates = [
        c for c in job.candidates
        if (c.status == "approved" if only_approved else c.status != "rejected")
    ]
    # 若教师未逐题点通过，允许发布全部 pending（视为默认通过）
    if only_approved and not candidates:
        candidates = [c for c in job.candidates if c.status == "pending"]
        for c in candidates:
            c.status = "approved"

    if not candidates:
        raise ValueError("没有可入库的题目，请先勾选或通过候选题")

    job.status = "publishing"
    db.flush()

    created = 0
    skipped_dup = 0
    created_kps = 0
    kp_cache: dict[tuple[int, int, str], KnowledgePoint] = {}

    def ensure_kp(chapter_id: int, class_id: int, name: str) -> KnowledgePoint | None:
        nonlocal created_kps
        name = (name or "").strip()
        if not name or not chapter_id:
            return None
        key = (chapter_id, class_id, name.lower())
        if key in kp_cache:
            return kp_cache[key]
        existing = db.scalar(
            select(KnowledgePoint).where(
                KnowledgePoint.chapter_id == chapter_id,
                KnowledgePoint.class_id == class_id,
                KnowledgePoint.name == name,
            )
        )
        if existing:
            kp_cache[key] = existing
            return existing
        kp = KnowledgePoint(
            chapter_id=chapter_id,
            class_id=class_id,
            agent_id=job.agent_id,
            name=name,
        )
        db.add(kp)
        db.flush()
        created_kps += 1
        kp_cache[key] = kp
        return kp

    for cand in candidates:
        if not cand.stem.strip() or not cand.chapter_id:
            continue
        chash = cand.content_hash or stem_hash(cand.stem)
        for cid in class_ids:
            # 去重：同班级同题干 hash
            dup = db.scalar(
                select(QuestionBank.id).where(
                    QuestionBank.class_id == cid,
                    QuestionBank.content_hash == chash,
                )
            )
            if dup:
                skipped_dup += 1
                continue
            # 兼容旧数据无 content_hash：再按 stem 粗查
            if not dup:
                old = db.scalar(
                    select(QuestionBank.id).where(
                        QuestionBank.class_id == cid,
                        QuestionBank.stem == cand.stem,
                    )
                )
                if old:
                    skipped_dup += 1
                    continue

            kp_id = cand.kp_id
            if cand.new_kp_name:
                kp = ensure_kp(cand.chapter_id, cid, cand.new_kp_name)
                if kp:
                    kp_id = kp.id
            elif kp_id:
                # 主知识点按班级复制：若原 kp 属其他班，需在本班建同名
                src_kp = db.get(KnowledgePoint, kp_id)
                if src_kp and src_kp.class_id != cid:
                    kp = ensure_kp(cand.chapter_id, cid, src_kp.name)
                    kp_id = kp.id if kp else None

            for extra_name in (cand.extra_kp_names_json or []):
                ensure_kp(cand.chapter_id, cid, str(extra_name))

            q = QuestionBank(
                chapter_id=cand.chapter_id,
                class_id=cid,
                agent_id=job.agent_id,
                kp_id=kp_id,
                type=cand.type or "简答题",
                stem=cand.stem,
                options_json=cand.options_json or [],
                answer=cand.answer or "",
                analysis=cand.analysis or "",
                source_import_job_id=job.id,
                source_page=cand.source_page,
                original_number=cand.original_number or None,
                content_hash=chash,
                extra_chapter_ids_json=cand.extra_chapter_ids_json or [],
                extra_kp_names_json=cand.extra_kp_names_json or [],
            )
            db.add(q)
            created += 1

    job.status = "completed"
    job.progress = 100
    job.completed_at = datetime.utcnow()
    stats = dict(job.stats_json or {})
    stats.update({
        "published": created,
        "skipped_dup": skipped_dup,
        "created_kps": created_kps,
    })
    job.stats_json = stats
    db.commit()
    return {
        "ok": True,
        "published": created,
        "skipped_dup": skipped_dup,
        "created_kps": created_kps,
        "job_id": job.id,
    }
