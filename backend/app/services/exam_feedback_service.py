"""考核报告反馈：单题追问、判卷反馈、教师介入。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Chapter,
    Exam,
    ExamGradingFeedback,
    ExamIntervention,
    ExamQuestion,
    ExamQuestionFollowup,
    ExamReport,
    User,
)
from ..services import recommend_service
from ..services.enrollment import get_student_class_for_course
from ..services.llm_provider import get_provider
from ..services.rag_service import retrieve_async, _build_context
from ..services.exam_service import compute_total_score

REWARD_AGREE = 1
REWARD_DISAGREE_PENDING = 0
REWARD_STUDENT_RIGHT = 5
REWARD_STUDENT_WRONG = -2
REWARD_PARTIAL = 2
# 教师自测反馈：奖惩力度约为学生的 2 倍
REWARD_TEACHER_AGREE = 2
REWARD_TEACHER_DISAGREE = -4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_question_by_idx(exam: Exam, idx: int) -> ExamQuestion | None:
    for q in exam.questions:
        if q.idx == idx:
            return q
    return None


def question_context_dict(q: ExamQuestion, exam: Exam) -> dict:
    return {
        "idx": q.idx,
        "type": q.type,
        "stem": q.stem,
        "options": q.options_json or [],
        "user_answer": q.user_answer,
        "correct_answer": q.correct_answer,
        "is_correct": q.is_correct,
        "ai_score": q.ai_score,
        "ai_feedback": q.ai_feedback,
        "analysis": q.analysis or "",
        "kp_name": q.kp_name or "",
        "chapter_id": exam.chapter_id,
        "max_score": 100,
    }


def enrich_intervention_context(db: Session, iv: ExamIntervention) -> dict:
    """合并快照与最新题目数据，供教师处理争议时展示完整信息。"""
    stored = dict(iv.context_json or {})
    exam = db.get(Exam, iv.exam_id)
    if exam:
        q = get_question_by_idx(exam, iv.question_idx)
        if q:
            stored = {**stored, **question_context_dict(q, exam)}
    if "max_score" not in stored:
        stored["max_score"] = 100
    return stored


def _build_exam_ask_messages(
    q: ExamQuestion,
    exam: Exam,
    user_question: str,
    history: list[dict],
    context_hits: list[dict],
    recommendations_text: str,
) -> list[dict]:
    ctx = question_context_dict(q, exam)
    system = f"""你是课程学习辅导助手。学生刚完成章节考核，正在查看报告并对某道题追问。

【当前题目】
题型：{ctx['type']}
题干：{ctx['stem']}
学生作答：{ctx['user_answer'] or '（未作答）'}
参考答案：{ctx['correct_answer']}
AI 评分：{ctx['ai_score']} 分（{'正确' if ctx['is_correct'] else '错误/部分正确'}）
AI 评语：{ctx['ai_feedback']}
{f"解析：{ctx['analysis']}" if ctx['analysis'] else ''}
{f"知识点：{ctx['kp_name']}" if ctx['kp_name'] else ''}

【课程资料检索片段】
{_build_context(context_hits)}

【推荐复习资料】
{recommendations_text or '（暂无匹配资料）'}

请结合题目与资料，用清晰易懂的语言解答学生追问；若涉及代码请给出简短示例。
"""
    messages = [{"role": "system", "content": system}]
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_question})
    return messages


async def prepare_question_ask(
    db: Session,
    exam: Exam,
    idx: int,
    user: User,
    question: str,
    class_ids: list[int] | None,
    course_id: int | None,
):
    """检索资料并构建流式问答上下文。"""
    q = get_question_by_idx(exam, idx)
    if not q:
        raise ValueError("题目不存在")
    search_q = f"{q.stem} {q.kp_name or ''} {question}".strip()
    hits = await retrieve_async(
        search_q,
        chapter_id=exam.chapter_id,
        class_ids=class_ids,
        course_id=course_id,
    )
    recommendations = recommend_service.recommend_from_hits(db, hits)
    rec_text = recommend_service.format_for_prompt(recommendations)

    prev = db.scalars(
        select(ExamQuestionFollowup)
        .where(
            ExamQuestionFollowup.exam_id == exam.id,
            ExamQuestionFollowup.question_idx == idx,
            ExamQuestionFollowup.user_id == user.id,
        )
        .order_by(ExamQuestionFollowup.id)
    ).all()
    history = []
    for row in prev:
        history.append({"role": "user", "content": row.question})
        if row.answer:
            history.append({"role": "assistant", "content": row.answer})

    messages = _build_exam_ask_messages(q, exam, question, history, hits, rec_text)
    provider = get_provider()
    return provider, provider.stream_chat(messages), recommendations


def save_followup(
    db: Session,
    exam_id: int,
    idx: int,
    user_id: int,
    question: str,
    answer: str,
    recommendations: list[dict],
) -> ExamQuestionFollowup:
    row = ExamQuestionFollowup(
        exam_id=exam_id,
        question_idx=idx,
        user_id=user_id,
        question=question,
        answer=answer,
        recommendations_json=recommendations,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_followups(db: Session, exam_id: int, idx: int, user_id: int) -> list[dict]:
    rows = db.scalars(
        select(ExamQuestionFollowup)
        .where(
            ExamQuestionFollowup.exam_id == exam_id,
            ExamQuestionFollowup.question_idx == idx,
            ExamQuestionFollowup.user_id == user_id,
        )
        .order_by(ExamQuestionFollowup.id)
    ).all()
    return [_followup_to_dict(r) for r in rows]


def _followup_to_dict(r: ExamQuestionFollowup) -> dict:
    return {
        "id": r.id,
        "question": r.question,
        "answer": r.answer,
        "recommendations": r.recommendations_json or [],
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def list_followups_grouped(
    db: Session,
    exam_id: int,
    user_id: int | None = None,
) -> dict[int, list[dict]]:
    """按题号分组的追问记录（用于报告页一次性加载）。"""
    q = select(ExamQuestionFollowup).where(ExamQuestionFollowup.exam_id == exam_id)
    if user_id is not None:
        q = q.where(ExamQuestionFollowup.user_id == user_id)
    rows = db.scalars(q.order_by(ExamQuestionFollowup.id)).all()
    grouped: dict[int, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r.question_idx, []).append(_followup_to_dict(r))
    return grouped


def _apply_credit(db: Session, user: User, delta: int) -> int:
    user.feedback_credit = (user.feedback_credit or 0) + delta
    db.add(user)
    return user.feedback_credit


def _intervention_to_dict(iv: ExamIntervention) -> dict:
    return {
        "id": iv.id,
        "status": iv.status,
        "trigger": iv.trigger,
        "student_message": iv.student_message or "",
        "teacher_response": iv.teacher_response or "",
        "resolved_score": iv.resolved_score,
        "created_at": iv.created_at.isoformat() if iv.created_at else None,
        "resolved_at": iv.resolved_at.isoformat() if iv.resolved_at else None,
    }


def _get_intervention(
    db: Session, exam_id: int, question_idx: int, student_id: int,
) -> ExamIntervention | None:
    """每题每学生仅一条介入记录（取最新）。"""
    return db.scalar(
        select(ExamIntervention)
        .where(
            ExamIntervention.exam_id == exam_id,
            ExamIntervention.question_idx == question_idx,
            ExamIntervention.student_id == student_id,
        )
        .order_by(ExamIntervention.id.desc())
        .limit(1)
    )


def _pending_intervention(
    db: Session, exam_id: int, question_idx: int, student_id: int,
) -> ExamIntervention | None:
    iv = _get_intervention(db, exam_id, question_idx, student_id)
    return iv if iv and iv.status == "pending" else None


def should_auto_intervene(q: ExamQuestion, verdict: str, comment: str) -> bool:
    """学生标记判卷有误时是否自动申请教师介入（现统一为 True）。"""
    return verdict == "disagree"


def apply_teacher_ai_correction(
    db: Session,
    q: ExamQuestion,
    comment: str = "",
) -> None:
    """教师自测标记 AI 判卷有误：在题目上留下校正记录，供后续模型优化参考。"""
    note = f"[教师校正] {comment.strip()}" if (comment or "").strip() else "[教师校正] AI 判卷有误"
    prev = (q.ai_feedback or "").strip()
    if note not in prev:
        q.ai_feedback = f"{prev}\n{note}".strip() if prev else note
    db.add(q)


def _get_or_create_intervention(
    db: Session,
    exam: Exam,
    q: ExamQuestion,
    student: User,
    class_id: int,
    trigger: str,
    student_message: str,
) -> tuple[ExamIntervention, bool]:
    """获取或创建介入记录，保证每题每学生仅一条。返回 (记录, 是否新建)。"""
    existing = _get_intervention(db, exam.id, q.idx, student.id)
    if existing:
        if (
            student_message
            and existing.status == "pending"
            and student_message.strip() not in (existing.student_message or "")
        ):
            prev = (existing.student_message or "").strip()
            existing.student_message = f"{prev}\n{student_message.strip()}".strip() if prev else student_message.strip()
            db.add(existing)
        return existing, False

    row = ExamIntervention(
        exam_id=exam.id,
        question_idx=q.idx,
        student_id=student.id,
        class_id=class_id,
        trigger=trigger,
        status="pending",
        student_message=student_message,
        context_json=question_context_dict(q, exam),
    )
    db.add(row)
    db.flush()
    return row, True


def create_intervention(
    db: Session,
    exam: Exam,
    q: ExamQuestion,
    student: User,
    class_id: int,
    trigger: str,
    student_message: str,
) -> ExamIntervention | None:
    row, _ = _get_or_create_intervention(db, exam, q, student, class_id, trigger, student_message)
    db.commit()
    db.refresh(row)
    return row


def submit_grading_feedback(
    db: Session,
    exam: Exam,
    idx: int,
    user: User,
    verdict: str,
    comment: str = "",
) -> dict:
    if verdict not in ("agree", "disagree"):
        raise ValueError("verdict 须为 agree 或 disagree")
    is_self_test = user.role in ("teacher", "admin") and exam.user_id == user.id
    if user.role != "student" and not is_self_test:
        raise ValueError("仅学生或本人自测可提交此类反馈，审阅学生报告请使用教师复核接口")
    q = get_question_by_idx(exam, idx)
    if not q:
        raise ValueError("题目不存在")

    class_id: int | None = None
    if user.role == "student":
        chapter = db.get(Chapter, exam.chapter_id)
        class_id = get_student_class_for_course(db, user, chapter.course_id) if chapter else None
        if not class_id:
            raise ValueError("未加入课程班级")

    if is_self_test:
        reward = REWARD_TEACHER_AGREE if verdict == "agree" else REWARD_TEACHER_DISAGREE
    else:
        reward = REWARD_AGREE if verdict == "agree" else REWARD_DISAGREE_PENDING

    existing = db.scalar(
        select(ExamGradingFeedback).where(
            ExamGradingFeedback.exam_question_id == q.id,
            ExamGradingFeedback.user_id == user.id,
        )
    )
    if existing:
        raise ValueError("本题已提交判卷反馈，不可重复提交或修改")

    fb = ExamGradingFeedback(
        exam_question_id=q.id,
        user_id=user.id,
        verdict=verdict,
        comment=comment,
        reward_delta=reward,
    )
    db.add(fb)
    _apply_credit(db, user, reward)

    direct_ai_correction = False
    if is_self_test and verdict == "disagree":
        fb.teacher_confirmed = True
        apply_teacher_ai_correction(db, q, comment)
        direct_ai_correction = True
    elif is_self_test and verdict == "agree":
        fb.teacher_confirmed = None

    intervention = None
    intervention_existing = False
    if user.role == "student" and verdict == "disagree":
        if not class_id:
            raise ValueError("未加入课程班级，无法申请教师介入")
        msg = comment or f"我认为第 {idx} 题 AI 判卷有误（得分 {q.ai_score}）"
        intervention, intervention_existing = _get_or_create_intervention(
            db, exam, q, user, class_id, "auto", msg,
        )

    db.commit()
    db.refresh(fb)
    if intervention:
        db.refresh(intervention)
    return {
        "feedback_id": fb.id,
        "verdict": fb.verdict,
        "reward_delta": fb.reward_delta,
        "direct_ai_correction": direct_ai_correction,
        "question_ai_feedback": q.ai_feedback if direct_ai_correction else None,
        "intervention_id": intervention.id if intervention else None,
        "intervention_auto": intervention.trigger == "auto" if intervention else False,
        "intervention_existing": intervention_existing,
    }


def submit_teacher_grading_review(
    db: Session,
    exam: Exam,
    idx: int,
    teacher: User,
    verdict: str,
    comment: str = "",
) -> dict:
    """教师对 AI 判卷结果进行复核（无信誉分/自动介入）。"""
    if verdict not in ("agree", "disagree"):
        raise ValueError("verdict 须为 agree 或 disagree")
    q = get_question_by_idx(exam, idx)
    if not q:
        raise ValueError("题目不存在")

    existing = db.scalar(
        select(ExamGradingFeedback).where(
            ExamGradingFeedback.exam_question_id == q.id,
            ExamGradingFeedback.user_id == teacher.id,
        )
    )
    if existing:
        existing.verdict = verdict
        existing.comment = comment
        fb = existing
    else:
        fb = ExamGradingFeedback(
            exam_question_id=q.id,
            user_id=teacher.id,
            verdict=verdict,
            comment=comment,
            reward_delta=0,
        )
        db.add(fb)

    # 教师复核可同步更新学生异议的处理状态
    student_fb = db.scalar(
        select(ExamGradingFeedback).where(
            ExamGradingFeedback.exam_question_id == q.id,
            ExamGradingFeedback.user_id == exam.user_id,
            ExamGradingFeedback.verdict == "disagree",
        )
    )
    if student_fb and student_fb.teacher_confirmed is None:
        if verdict == "disagree":
            student_fb.teacher_confirmed = True
        elif verdict == "agree":
            student_fb.teacher_confirmed = False

    db.commit()
    db.refresh(fb)
    return {
        "feedback_id": fb.id,
        "verdict": fb.verdict,
        "reviewer_name": teacher.display_name or teacher.username,
    }


def request_teacher_intervention(
    db: Session,
    exam: Exam,
    idx: int,
    user: User,
    message: str,
) -> dict:
    if user.role == "student":
        raise ValueError("请通过「判卷有误」反馈，系统将自动向教师提交介入申请")
    raise ValueError("教师/管理员自测无需申请教师介入")


def get_student_intervention(
    db: Session,
    exam: Exam,
    idx: int,
    user: User,
) -> dict | None:
    iv = _get_intervention(db, exam.id, idx, user.id)
    if not iv:
        return None
    return _intervention_to_dict(iv)


def get_report_feedback_meta(
    db: Session,
    exam: Exam,
    student_user_id: int,
    viewer: User | None = None,
) -> dict:
    """报告页每题反馈、教师复核与追问记录。"""
    q_ids = {q.idx: q.id for q in exam.questions}
    qid_to_idx = {v: k for k, v in q_ids.items()}

    fb_rows = db.scalars(
        select(ExamGradingFeedback).where(
            ExamGradingFeedback.exam_question_id.in_(list(q_ids.values())),
        )
    ).all()
    user_ids = {fb.user_id for fb in fb_rows}
    users = {
        u.id: u
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}

    student_fb_by_idx: dict[int, dict] = {}
    teacher_reviews_by_idx: dict[int, dict] = {}
    my_teacher_review_by_idx: dict[int, dict] = {}

    for fb in fb_rows:
        idx = qid_to_idx.get(fb.exam_question_id)
        if idx is None:
            continue
        u = users.get(fb.user_id)
        role = u.role if u else "student"
        item = {
            "verdict": fb.verdict,
            "comment": fb.comment,
            "reward_delta": fb.reward_delta,
            "teacher_confirmed": fb.teacher_confirmed,
            "reviewer_id": fb.user_id,
            "reviewer_name": (u.display_name or u.username) if u else "",
        }
        if fb.user_id == student_user_id:
            student_fb_by_idx[idx] = item
        elif role in ("teacher", "admin"):
            teacher_reviews_by_idx[idx] = item
            if viewer and fb.user_id == viewer.id:
                my_teacher_review_by_idx[idx] = item

    interventions = db.scalars(
        select(ExamIntervention).where(
            ExamIntervention.exam_id == exam.id,
            ExamIntervention.student_id == student_user_id,
        ).order_by(ExamIntervention.question_idx, ExamIntervention.id.desc())
    ).all()
    iv_by_idx: dict[int, dict] = {}
    for iv in interventions:
        if iv.question_idx in iv_by_idx:
            continue
        if iv.status == "dismissed":
            continue
        fb = student_fb_by_idx.get(iv.question_idx)
        if fb and fb.get("verdict") != "disagree":
            continue
        iv_by_idx[iv.question_idx] = _intervention_to_dict(iv)

    followups = list_followups_grouped(db, exam.id, student_user_id)

    return {
        "grading_feedback": student_fb_by_idx,
        "teacher_reviews": teacher_reviews_by_idx,
        "my_teacher_reviews": my_teacher_review_by_idx,
        "interventions": iv_by_idx,
        "followups": followups,
    }


def list_teacher_interventions(
    db: Session,
    teacher: User,
    managed_class_ids: list[int],
    status: str | None = None,
    class_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    if not managed_class_ids:
        return {"total": 0, "page": page, "size": size, "items": []}
    class_ids = [class_id] if class_id is not None else managed_class_ids
    base = select(ExamIntervention).where(
        ExamIntervention.class_id.in_(class_ids),
        ExamIntervention.status != "dismissed",
    )
    if status:
        base = base.where(ExamIntervention.status == status)
    rows = db.scalars(
        base.order_by(ExamIntervention.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    resolver_ids = {iv.resolved_by for iv in rows if iv.resolved_by}
    resolvers = {
        u.id: u
        for u in db.scalars(select(User).where(User.id.in_(resolver_ids or {0}))).all()
    }

    items = []
    for iv in rows:
        exam = db.get(Exam, iv.exam_id)
        student = db.get(User, iv.student_id)
        ch = db.get(Chapter, exam.chapter_id) if exam else None
        resolver = resolvers.get(iv.resolved_by) if iv.resolved_by else None
        items.append({
            "id": iv.id,
            "exam_id": iv.exam_id,
            "question_idx": iv.question_idx,
            "student_id": iv.student_id,
            "student_name": student.display_name if student else "",
            "student_username": student.username if student else "",
            "chapter_title": ch.title if ch else "",
            "class_id": iv.class_id,
            "trigger": iv.trigger,
            "status": iv.status,
            "student_message": iv.student_message,
            "teacher_response": iv.teacher_response,
            "resolved_by_id": iv.resolved_by,
            "resolved_by_name": (resolver.display_name or resolver.username) if resolver else "",
            "context": enrich_intervention_context(db, iv),
            "resolved_score": iv.resolved_score,
            "created_at": iv.created_at.isoformat() if iv.created_at else None,
            "resolved_at": iv.resolved_at.isoformat() if iv.resolved_at else None,
        })
    return {"total": total, "page": page, "size": size, "items": items}


def get_intervention_detail(db: Session, iv_id: int) -> ExamIntervention | None:
    return db.get(ExamIntervention, iv_id)


def resolve_intervention(
    db: Session,
    iv: ExamIntervention,
    teacher: User,
    action: str,
    teacher_response: str = "",
    resolved_score: float | None = None,
    student_feedback_correct: bool | None = None,
) -> dict:
    """教师处理介入：确认并改分（不可驳回）。"""
    if iv.status != "pending":
        raise ValueError("该申请已处理")
    if action != "resolved":
        raise ValueError("教师只能确认处理介入申请，不能驳回")
    exam = db.get(Exam, iv.exam_id)
    if not exam:
        raise ValueError("考核不存在")

    q = get_question_by_idx(exam, iv.question_idx)
    student = db.get(User, iv.student_id)

    iv.status = "resolved"
    iv.teacher_response = teacher_response
    iv.resolved_by = teacher.id
    iv.resolved_at = _utcnow()
    if resolved_score is not None and q:
        q.ai_score = resolved_score
        q.is_correct = resolved_score >= 60
        iv.resolved_score = resolved_score
        report = db.scalar(select(ExamReport).where(ExamReport.exam_id == exam.id))
        if report:
            report.total_score = compute_total_score(exam)
    if student:
        fb = db.scalar(
            select(ExamGradingFeedback).where(
                ExamGradingFeedback.exam_question_id == q.id if q else -1,
                ExamGradingFeedback.user_id == iv.student_id,
                ExamGradingFeedback.verdict == "disagree",
            )
        )
        if fb and fb.teacher_confirmed is None:
            if student_feedback_correct is True:
                fb.teacher_confirmed = True
                delta = REWARD_STUDENT_RIGHT - fb.reward_delta
                fb.reward_delta = REWARD_STUDENT_RIGHT
            elif student_feedback_correct is False:
                fb.teacher_confirmed = False
                delta = REWARD_STUDENT_WRONG - fb.reward_delta
                fb.reward_delta = REWARD_STUDENT_WRONG
            else:
                fb.teacher_confirmed = True
                delta = REWARD_PARTIAL - fb.reward_delta
                fb.reward_delta = REWARD_PARTIAL
            _apply_credit(db, student, delta)

    db.commit()
    return {
        "id": iv.id,
        "status": iv.status,
        "resolved_score": iv.resolved_score,
        "resolved_by_name": teacher.display_name or teacher.username,
        "feedback_credit": student.feedback_credit if student else None,
    }


def get_admin_feedback_overview(db: Session) -> dict:
    """管理员：模型判卷反馈与强化训练概况。"""
    from ..models import ExamQuestionFollowup

    all_fb = db.scalars(select(ExamGradingFeedback)).all()
    user_map = {
        u.id: u
        for u in db.scalars(select(User).where(User.id.in_({f.user_id for f in all_fb} or {0}))).all()
    }

    student_agree = student_disagree = 0
    confirmed_right = confirmed_wrong = pending_confirm = 0
    teacher_agree = teacher_disagree = 0

    for fb in all_fb:
        u = user_map.get(fb.user_id)
        if not u:
            continue
        if u.role == "student":
            if fb.verdict == "agree":
                student_agree += 1
            else:
                student_disagree += 1
            if fb.teacher_confirmed is True:
                confirmed_right += 1
            elif fb.teacher_confirmed is False:
                confirmed_wrong += 1
            elif fb.verdict == "disagree":
                pending_confirm += 1
        elif u.role in ("teacher", "admin"):
            if fb.verdict == "agree":
                teacher_agree += 1
            else:
                teacher_disagree += 1

    iv_pending = db.scalar(
        select(func.count()).select_from(ExamIntervention).where(ExamIntervention.status == "pending")
    ) or 0
    iv_resolved = db.scalar(
        select(func.count()).select_from(ExamIntervention).where(ExamIntervention.status == "resolved")
    ) or 0
    followup_total = db.scalar(select(func.count()).select_from(ExamQuestionFollowup)) or 0

    students = db.scalars(
        select(User).where(User.role == "student").order_by(User.feedback_credit.desc())
    ).all()
    credit_rank = [
        {
            "user_id": s.id,
            "username": s.username,
            "display_name": s.display_name,
            "feedback_credit": s.feedback_credit or 0,
        }
        for s in students if (s.feedback_credit or 0) != 0
    ][:20]

    judged = confirmed_right + confirmed_wrong
    accuracy = round(confirmed_right / judged * 100, 1) if judged else None

    return {
        "student_feedback_total": student_agree + student_disagree,
        "student_agree": student_agree,
        "student_disagree": student_disagree,
        "teacher_review_total": teacher_agree + teacher_disagree,
        "teacher_agree": teacher_agree,
        "teacher_disagree": teacher_disagree,
        "confirmed_right": confirmed_right,
        "confirmed_wrong": confirmed_wrong,
        "pending_confirm": pending_confirm,
        "feedback_accuracy_pct": accuracy,
        "interventions_pending": iv_pending,
        "interventions_resolved": iv_resolved,
        "followup_total": followup_total,
        "credit_rank": credit_rank,
    }


def list_admin_feedback_records(
    db: Session,
    page: int = 1,
    size: int = 20,
) -> dict:
    """管理员：判卷反馈明细。"""
    base = select(ExamGradingFeedback).order_by(ExamGradingFeedback.id.desc())
    total = db.scalar(select(func.count()).select_from(ExamGradingFeedback)) or 0
    rows = db.scalars(base.offset((page - 1) * size).limit(size)).all()

    user_ids = {r.user_id for r in rows}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids or {0}))).all()}

    q_ids = {r.exam_question_id for r in rows}
    questions = {q.id: q for q in db.scalars(select(ExamQuestion).where(ExamQuestion.id.in_(q_ids or {0}))).all()}
    exam_ids = {q.exam_id for q in questions.values()}
    exams = {e.id: e for e in db.scalars(select(Exam).where(Exam.id.in_(exam_ids or {0}))).all()}

    items = []
    for fb in rows:
        u = users.get(fb.user_id)
        q = questions.get(fb.exam_question_id)
        exam = exams.get(q.exam_id) if q else None
        items.append({
            "id": fb.id,
            "user_id": fb.user_id,
            "username": u.username if u else "",
            "display_name": u.display_name if u else "",
            "role": u.role if u else "",
            "exam_id": exam.id if exam else None,
            "question_idx": q.idx if q else None,
            "verdict": fb.verdict,
            "comment": fb.comment,
            "reward_delta": fb.reward_delta,
            "teacher_confirmed": fb.teacher_confirmed,
            "created_at": fb.created_at.isoformat() if fb.created_at else None,
        })
    return {"total": total, "page": page, "size": size, "items": items}
