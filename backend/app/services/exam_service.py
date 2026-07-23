"""章节考核服务：试卷生成 / 评分 / 评价报告。

生成策略：题库优先抽题；不足题型用 LLM 基于章节知识点动态补足。
评分策略：客观题提取首字母比对；简答题用 LLM 按「标准答案 + 维度」打分。
报告策略：LLM 按 3 维度生成评价 + 薄弱知识点列表 + 总分持久化。
"""
from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Agent,
    Chapter,
    ChapterProgress,
    Exam,
    ExamConfig,
    ExamQuestion,
    ExamReport,
    KnowledgePoint,
    QuestionBank,
    User,
)
from ..deps import get_exam_config
from .agent_access import get_shared_exam_config, is_adopted_snapshot, resolve_agent_for_exam, resolve_bank_class_ids
from .llm_provider import get_provider

TYPE_LABEL = {"选择题": "选择题", "判断题": "判断题", "简答题": "简答题"}


def _get_kp_names(
    db: Session,
    chapter_id: int,
    class_id: int | None = None,
    extra_class_ids: list[int] | None = None,
    agent: Agent | None = None,
) -> list[str]:
    class_ids = list(dict.fromkeys(
        ([class_id] if class_id else []) + (extra_class_ids or [])
    ))
    q = select(KnowledgePoint).where(KnowledgePoint.chapter_id == chapter_id)
    if agent and is_adopted_snapshot(agent):
        if class_ids:
            q = q.where(or_(
                KnowledgePoint.agent_id == agent.id,
                KnowledgePoint.class_id.in_(class_ids),
            ))
        else:
            q = q.where(KnowledgePoint.agent_id == agent.id)
    elif class_ids:
        q = q.where(KnowledgePoint.class_id.in_(class_ids))
    rows = db.scalars(q).all()
    return [r.name for r in rows]


def _llm_generate_questions(
    db: Session, chapter: Chapter, qtype: str, count: int, kp_names: list[str]
) -> list[dict]:
    """用 LLM 生成 count 道 qtype 题目（JSON 列表）。"""
    prompt = f"""你是C语言课程出题助手。请为「{chapter.title}」章节生成 {count} 道{qtype}。
知识点范围：{", ".join(kp_names) if kp_names else "该章节核心知识点"}。
章节描述：{chapter.description}

要求：
1. 题目难度适中，考察对知识点理解
2. 严格输出 JSON 数组，每个元素格式：
   - 选择题: {{"type":"选择题","stem":"...","options":["A. ...","B. ...","C. ...","D. ..."],"answer":"A","analysis":"..."}}
   - 判断题: {{"type":"判断题","stem":"...","options":["对","错"],"answer":"对","analysis":"..."}}
   - 简答题: {{"type":"简答题","stem":"...","options":[],"answer":"参考答案要点...","analysis":"评分要点：..."}}
3. 只输出 JSON，不要任何解释或 markdown 代码块
"""
    provider = get_provider()
    raw = _run_sync(provider, [{"role": "user", "content": prompt}])
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
        if raw.endswith("```"): raw = raw[:-3].strip()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        try:
            s = raw[raw.index("["):raw.rindex("]") + 1]
            items = json.loads(s)
        except Exception:
            items = []
    out = []
    for it in items[:count]:
        if not isinstance(it, dict): continue
        if it.get("type") != qtype: continue
        out.append({
            "type": qtype,
            "stem": it.get("stem", ""),
            "options_json": it.get("options", []),
            "correct_answer": it.get("answer", ""),
            "analysis": it.get("analysis", ""),
        })
    return out


def _run_sync(provider, messages: list[dict]) -> str:
    """同步运行 provider.chat（在 sync 上下文中调用）。"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import threading
            result: list[str] = []
            def _run():
                new_loop = asyncio.new_event_loop()
                try:
                    result.append(new_loop.run_until_complete(provider.chat(messages)))
                finally:
                    new_loop.close()
            t = threading.Thread(target=_run); t.start(); t.join()
            return result[0] if result else ""
    except RuntimeError:
        pass
    return asyncio.run(provider.chat(messages))


def generate_paper(
    db: Session,
    user: User,
    chapter_id: int,
    class_id: int | None = None,
    *,
    teacher_test: bool = False,
    agent_id: int | None = None,
) -> tuple[Exam, list[str]]:
    """按章节考核配置生成试卷。返回 (exam, warnings)。"""
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise ValueError("章节不存在")
    effective_class_id = class_id
    if not effective_class_id:
        if user.role == "student" and chapter.course_id:
            from .enrollment import get_student_class_for_course
            effective_class_id = get_student_class_for_course(db, user, chapter.course_id)
    if not effective_class_id:
        raise ValueError("尚未加入该课程班级，无法开始考核")

    agent: Agent | None = resolve_agent_for_exam(
        db, user, effective_class_id, chapter.course_id, agent_id,
    )
    cfg = get_shared_exam_config(db, chapter_id, effective_class_id, agent)
    if not cfg:
        raise ValueError("该章节未为本班配置考核（共享源班级亦无配置）")

    shared_class_ids = [
        c for c in resolve_bank_class_ids(db, agent, effective_class_id)
        if c != effective_class_id
    ]

    # 检查考核次数上限（教师测试不受限）
    if not teacher_test and cfg.max_attempts and cfg.max_attempts > 0:
        existing_count = db.scalar(
            select(func.count()).select_from(
                select(Exam).where(
                    Exam.user_id == user.id,
                    Exam.chapter_id == chapter_id,
                ).subquery()
            )
        ) or 0
        if existing_count >= cfg.max_attempts:
            raise ValueError(f"该章节考核次数已达上限（{cfg.max_attempts}次），无法再次开考")

    config: dict[str, Any] = cfg.config_json or {}
    kp_names = config.get("knowledge_points") or _get_kp_names(
        db, chapter_id, effective_class_id, shared_class_ids, agent=agent,
    )
    warnings: list[str] = []

    exam = Exam(user_id=user.id, chapter_id=chapter_id, status="ongoing")
    db.add(exam); db.flush()

    idx = 0
    bank_class_ids = resolve_bank_class_ids(db, agent, effective_class_id)
    for qtype, count in config.items():
        if qtype == "knowledge_points" or not isinstance(count, int):
            continue
        bank_q = select(QuestionBank).where(
            QuestionBank.chapter_id == chapter_id,
            QuestionBank.type == qtype,
        )
        if agent and is_adopted_snapshot(agent):
            bank_q = bank_q.where(or_(
                QuestionBank.agent_id == agent.id,
                QuestionBank.class_id.in_(bank_class_ids),
            ))
        else:
            bank_q = bank_q.where(QuestionBank.class_id.in_(bank_class_ids))
        bank_rows = db.scalars(bank_q).all()
        random.shuffle(bank_rows)
        needed = count
        for bq in bank_rows[:needed]:
            idx += 1
            # 查知识点名
            kp = db.get(KnowledgePoint, bq.kp_id) if bq.kp_id else None
            db.add(ExamQuestion(
                exam_id=exam.id, idx=idx, source="bank", type=qtype,
                stem=bq.stem, options_json=bq.options_json or [],
                correct_answer=bq.answer, user_answer="", is_correct=None,
                analysis=bq.analysis or "",
                kp_name=kp.name if kp else "",
            ))
        shortfall = needed - len(bank_rows[:needed])
        if shortfall > 0:
            try:
                gen = _llm_generate_questions(db, chapter, qtype, shortfall, kp_names)
            except Exception as e:
                gen = []
                warnings.append(f"{qtype} LLM 生成失败: {e}")
            if len(gen) < shortfall:
                warnings.append(f"{qtype} 题量不足：需 {needed} 道，题库 {len(bank_rows)} 道，LLM 生成 {len(gen)} 道，缺 {shortfall - len(gen)} 道")
            for g in gen:
                idx += 1
                db.add(ExamQuestion(
                    exam_id=exam.id, idx=idx, source="llm", type=qtype,
                    stem=g["stem"], options_json=g.get("options_json", []),
                    correct_answer=g.get("correct_answer", ""), user_answer="",
                    analysis=g.get("analysis", ""),
                    kp_name="",
                ))
    if idx == 0:
        warnings.append("试卷无题目，请检查题库与考核配置")
    db.commit()
    db.refresh(exam)
    return exam, warnings


def save_answer(db: Session, exam: Exam, idx: int, answer: str) -> None:
    q = db.scalar(select(ExamQuestion).where(
        ExamQuestion.exam_id == exam.id, ExamQuestion.idx == idx
    ))
    if q:
        q.user_answer = answer
        db.commit()


def _normalize_answer(ans: str) -> str:
    """提取答案关键标识：选择题取首字母(A/B/C/D)，判断题取「对/错」。"""
    ans = (ans or "").strip()
    if not ans:
        return ""
    # 选择题：A / A. xxx / A、xxx → A
    m = re.match(r"^([A-Da-d])[\s.、．:：]?", ans)
    if m:
        return m.group(1).upper()
    # 判断题
    if ans in ("对", "正确", "T", "True", "true", "√"):
        return "对"
    if ans in ("错", "错误", "F", "False", "false", "×"):
        return "错"
    return ans.strip().upper()


def _grade_objective(q: ExamQuestion) -> tuple[bool, float]:
    user = _normalize_answer(q.user_answer or "")
    correct = _normalize_answer(q.correct_answer or "")
    ok = user == correct
    return ok, 100.0 if ok else 0.0


def _grade_subjective(db: Session, q: ExamQuestion) -> tuple[bool, float, str]:
    """LLM 评分简答题，返回 (是否合格, 0-100 分, 评语)。"""
    prompt = f"""你是C语言课程阅卷助手。请对学生的简答题作答评分。

题目：{q.stem}
参考答案：{q.correct_answer}
学生作答：{q.user_answer}

评分要求：
- 0-100 分，关键要点覆盖度为主
- 输出 JSON：{{"score": 数字, "feedback": "评语，指出对错与不足"}}

只输出 JSON。
"""
    provider = get_provider()
    raw = _run_sync(provider, [{"role": "user", "content": prompt}])
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
        if raw.endswith("```"): raw = raw[:-3].strip()
    try:
        obj = json.loads(raw)
        score = float(obj.get("score", 60))
        feedback = obj.get("feedback", "")
    except Exception:
        score = 60.0; feedback = "评分失败，默认给分"
    return score >= 60, score, feedback


def grade_exam(db: Session, exam: Exam) -> Exam:
    """评分全部题目。"""
    for q in exam.questions:
        if not (q.user_answer or "").strip():
            q.is_correct = False
            q.ai_score = 0.0
            q.ai_feedback = "未作答"
            continue
        if q.type in ("选择题", "判断题"):
            ok, score = _grade_objective(q)
            q.is_correct = ok
            q.ai_score = score
            q.ai_feedback = "正确" if ok else f"错误，正确答案: {q.correct_answer}"
        else:
            ok, score, feedback = _grade_subjective(db, q)
            q.is_correct = ok
            q.ai_score = score
            q.ai_feedback = feedback
    exam.status = "submitted"
    exam.submitted_at = datetime.now(timezone.utc)
    db.commit()
    return exam


def compute_total_score(exam: Exam) -> float:
    """计算总分（各题 ai_score 平均值）。"""
    scores = [q.ai_score or 0 for q in exam.questions]
    return round(sum(scores) / max(len(scores), 1), 1)


def generate_report(db: Session, exam: Exam) -> ExamReport:
    """生成 3 维度学习评价报告 + 薄弱知识点 + 总分。"""
    chapter = db.get(Chapter, exam.chapter_id)
    total_score = compute_total_score(exam)
    q_summary = "\n".join([
        f"[{q.type}] 题:{q.stem[:60]}\n  学生答:{(q.user_answer or '')[:60]}\n  正确答:{q.correct_answer[:60]}\n  得分:{q.ai_score} 评语:{(q.ai_feedback or '')[:60]}"
        for q in exam.questions
    ])
    # 收集错题对应知识点
    wrong_kps = [q.stem[:30] for q in exam.questions if q.is_correct is False]

    prompt = f"""你是C语言课程学习评价助手。基于以下学生考核作答情况，生成学习评价报告。

章节：{chapter.title if chapter else ''}
总分：{total_score}
作答明细：
{q_summary}

请按以下 JSON 格式输出：
{{
  "dimensions": {{"知识掌握情况": 0-100, "基础概念掌握": 0-100, "综合应用能力": 0-100}},
  "weak_points": ["薄弱知识点1", "薄弱知识点2", ...],
  "summary": "总体评价，2-3句",
  "suggestions": "建议复习的知识点与学习方向，3-5条要点"
}}
只输出 JSON。
"""
    provider = get_provider()
    raw = _run_sync(provider, [{"role": "user", "content": prompt}])
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
        if raw.endswith("```"): raw = raw[:-3].strip()
    try:
        obj = json.loads(raw)
        dimensions = obj.get("dimensions", {})
        weak_points = obj.get("weak_points", [])
        summary = obj.get("summary", "")
        suggestions = obj.get("suggestions", "")
        # LLM 可能返回 list 而非 str，统一转为字符串
        if isinstance(summary, list):
            summary = " ".join(str(s) for s in summary)
        if isinstance(suggestions, list):
            suggestions = "\n".join(f"• {s}" for s in suggestions)
        if not isinstance(summary, str):
            summary = str(summary)
        if not isinstance(suggestions, str):
            suggestions = str(suggestions)
        if not isinstance(weak_points, list):
            weak_points = [str(weak_points)] if weak_points else []
    except Exception:
        scores = [q.ai_score or 0 for q in exam.questions]
        avg = sum(scores) / max(len(scores), 1)
        dimensions = {
            "知识掌握情况": avg, "基础概念掌握": avg, "综合应用能力": avg,
        }
        weak_points = wrong_kps[:5]
        summary = "评价生成失败，已按平均分估算。"
        suggestions = "建议复习错题对应知识点。"

    report = db.scalar(select(ExamReport).where(ExamReport.exam_id == exam.id))
    if report:
        report.dimensions_json = dimensions
        report.summary = summary
        report.suggestions = suggestions
        report.total_score = total_score
        report.weak_points = weak_points
    else:
        report = ExamReport(
            exam_id=exam.id, dimensions_json=dimensions,
            summary=summary, suggestions=suggestions,
            total_score=total_score, weak_points=weak_points,
        )
        db.add(report)

    # 更新章节进度
    p = db.scalar(select(ChapterProgress).where(
        ChapterProgress.user_id == exam.user_id,
        ChapterProgress.chapter_id == exam.chapter_id,
    ))
    if not p:
        p = ChapterProgress(user_id=exam.user_id, chapter_id=exam.chapter_id)
        db.add(p)
    p.status = "已完成"
    p.last_exam_id = exam.id

    db.commit()
    db.refresh(report)
    return report


def generate_fallback_report(db: Session, exam: Exam, error_msg: str = "") -> ExamReport:
    """生成降级报告（不调用 LLM，仅基于评分数据）。用于 generate_report 失败时兜底。"""
    total_score = compute_total_score(exam)
    scores = [q.ai_score or 0 for q in exam.questions]
    avg = sum(scores) / max(len(scores), 1)
    wrong_kps = [q.kp_name or q.stem[:20] for q in exam.questions if q.is_correct is False and q.kp_name]
    wrong_kps = list(dict.fromkeys(wrong_kps))[:5]  # 去重取前5

    dimensions = {
        "知识掌握情况": avg,
        "基础概念掌握": avg,
        "综合应用能力": avg,
    }
    summary = f"评价报告生成失败（{error_msg[:50]}），已按评分数据生成基础报告。总分 {total_score}。"
    suggestions = "建议复习以下错题对应的知识点：" + "、".join(wrong_kps) if wrong_kps else "建议复习错题对应知识点。"

    report = db.scalar(select(ExamReport).where(ExamReport.exam_id == exam.id))
    if report:
        report.dimensions_json = dimensions
        report.summary = summary
        report.suggestions = suggestions
        report.total_score = total_score
        report.weak_points = wrong_kps
    else:
        report = ExamReport(
            exam_id=exam.id, dimensions_json=dimensions,
            summary=summary, suggestions=suggestions,
            total_score=total_score, weak_points=wrong_kps,
        )
        db.add(report)

    # 更新章节进度
    p = db.scalar(select(ChapterProgress).where(
        ChapterProgress.user_id == exam.user_id,
        ChapterProgress.chapter_id == exam.chapter_id,
    ))
    if not p:
        p = ChapterProgress(user_id=exam.user_id, chapter_id=exam.chapter_id)
        db.add(p)
    p.status = "已完成"
    p.last_exam_id = exam.id

    db.commit()
    db.refresh(report)
    return report


def exam_to_dict(exam: Exam) -> dict:
    return {
        "id": exam.id, "chapter_id": exam.chapter_id, "status": exam.status,
        "started_at": exam.started_at.isoformat() if exam.started_at else None,
        "submitted_at": exam.submitted_at.isoformat() if exam.submitted_at else None,
        "questions": [
            {
                "idx": q.idx, "source": q.source, "type": q.type,
                "stem": q.stem, "options": q.options_json or [],
                "user_answer": q.user_answer,
                "kp_name": q.kp_name or "",
                **(
                    {"correct_answer": q.correct_answer, "is_correct": q.is_correct,
                     "ai_score": q.ai_score, "ai_feedback": q.ai_feedback,
                     "analysis": q.analysis or ""}
                    if exam.status == "submitted" else {}
                ),
            }
            for q in exam.questions
        ],
    }
