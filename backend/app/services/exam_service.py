"""章节考核服务：试卷生成 / 评分 / 评价报告。

生成策略：题库优先抽题；不足题型用 LLM 基于章节知识点动态补足。
评分策略：客观题直接判，简答题用 LLM 按「标准答案 + 维度」打分。
报告策略：LLM 按 4 维度生成评价。
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
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
from .llm_provider import get_provider

TYPE_LABEL = {"选择题": "选择题", "判断题": "判断题", "简答题": "简答题"}


def _get_kp_names(db: Session, chapter_id: int) -> list[str]:
    rows = db.scalars(select(KnowledgePoint).where(KnowledgePoint.chapter_id == chapter_id)).all()
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
    # 容错：剥离 markdown 代码块
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
        if raw.endswith("```"): raw = raw[:-3].strip()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        # 退化：尝试找到第一个 [ 到最后一个 ]
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
            # 已在事件循环中（FastAPI sync 路由会在 threadpool），新建 loop
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


def generate_paper(db: Session, user: User, chapter_id: int) -> Exam:
    """按章节考核配置生成试卷。"""
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise ValueError("章节不存在")
    cfg = db.scalar(select(ExamConfig).where(ExamConfig.chapter_id == chapter_id))
    if not cfg:
        raise ValueError("该章节未配置考核")

    config: dict[str, Any] = cfg.config_json or {}
    kp_names = config.get("knowledge_points") or _get_kp_names(db, chapter_id)

    exam = Exam(user_id=user.id, chapter_id=chapter_id, status="ongoing")
    db.add(exam); db.flush()

    idx = 0
    for qtype, count in config.items():
        if qtype == "knowledge_points" or not isinstance(count, int):
            continue
        # 1) 题库抽题
        bank_rows = db.scalars(
            select(QuestionBank).where(
                QuestionBank.chapter_id == chapter_id,
                QuestionBank.type == qtype,
            )
        ).all()
        random.shuffle(bank_rows)
        needed = count
        for bq in bank_rows[:needed]:
            idx += 1
            db.add(ExamQuestion(
                exam_id=exam.id, idx=idx, source="bank", type=qtype,
                stem=bq.stem, options_json=bq.options_json or [],
                correct_answer=bq.answer, user_answer="", is_correct=None,
            ))
        shortfall = needed - len(bank_rows[:needed])
        # 2) LLM 补足
        if shortfall > 0:
            gen = _llm_generate_questions(db, chapter, qtype, shortfall, kp_names)
            for g in gen:
                idx += 1
                db.add(ExamQuestion(
                    exam_id=exam.id, idx=idx, source="llm", type=qtype,
                    stem=g["stem"], options_json=g.get("options_json", []),
                    correct_answer=g.get("correct_answer", ""), user_answer="",
                ))
    db.commit()
    db.refresh(exam)
    return exam


def save_answer(db: Session, exam: Exam, idx: int, answer: str) -> None:
    q = db.scalar(select(ExamQuestion).where(
        ExamQuestion.exam_id == exam.id, ExamQuestion.idx == idx
    ))
    if q:
        q.user_answer = answer
        db.commit()


def _grade_objective(q: ExamQuestion) -> tuple[bool, float]:
    correct = (q.user_answer or "").strip().upper() == (q.correct_answer or "").strip().upper()
    return correct, 100.0 if correct else 0.0


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


def generate_report(db: Session, exam: Exam) -> ExamReport:
    """生成 4 维度学习评价报告。"""
    chapter = db.get(Chapter, exam.chapter_id)
    q_summary = "\n".join([
        f"[{q.type}] 题:{q.stem[:60]}\n  学生答:{q.user_answer[:60]}\n  正确答:{q.correct_answer[:60]}\n  得分:{q.ai_score} 评语:{q.ai_feedback[:60]}"
        for q in exam.questions
    ])
    prompt = f"""你是C语言课程学习评价助手。基于以下学生考核作答情况，生成学习评价报告。

章节：{chapter.title if chapter else ''}
作答明细：
{q_summary}

请按以下 4 个维度输出 JSON：
{{
  "dimensions": {{"知识掌握情况": 0-100, "基础概念掌握": 0-100, "综合分析能力": 0-100, "建议复习知识点": 0-100}},
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
        summary = obj.get("summary", "")
        suggestions = obj.get("suggestions", "")
    except Exception:
        # 退化：按平均分计算
        scores = [q.ai_score or 0 for q in exam.questions]
        avg = sum(scores) / max(len(scores), 1)
        dimensions = {
            "知识掌握情况": avg, "基础概念掌握": avg,
            "综合分析能力": avg, "建议复习知识点": avg,
        }
        summary = "评价生成失败，已按平均分估算。"
        suggestions = "建议复习错题对应知识点。"

    report = db.scalar(select(ExamReport).where(ExamReport.exam_id == exam.id))
    if report:
        report.dimensions_json = dimensions
        report.summary = summary
        report.suggestions = suggestions
    else:
        report = ExamReport(
            exam_id=exam.id, dimensions_json=dimensions,
            summary=summary, suggestions=suggestions,
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
                # 提交后才返回答案与评分
                **(
                    {"correct_answer": q.correct_answer, "is_correct": q.is_correct,
                     "ai_score": q.ai_score, "ai_feedback": q.ai_feedback}
                    if exam.status == "submitted" else {}
                ),
            }
            for q in exam.questions
        ],
    }
