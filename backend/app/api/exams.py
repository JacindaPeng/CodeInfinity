"""考核路由：学生端开始/答题/交卷/报告 + 教师端配置与题库 CRUD。

路由顺序：具体路径（/start, /history/mine, /config/*, /bank/*, /knowledge-points/*）
必须定义在 /{exam_id} 通配之前，避免被 {exam_id} 抢占匹配。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..deps import CurrentUser, DBSession, require_role
from ..models import (
    Chapter,
    Exam,
    ExamConfig,
    ExamReport,
    KnowledgePoint,
    QuestionBank,
)
from ..services import exam_service

router = APIRouter(prefix="/exams", tags=["exams"])


# ============ 具体路径（优先匹配） ============

class StartIn(BaseModel):
    chapter_id: int


@router.post("/start")
def start_exam(payload: StartIn, user: CurrentUser, db: DBSession) -> dict:
    try:
        exam = exam_service.generate_paper(db, user, payload.chapter_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"exam_id": exam.id, "questions": exam_service.exam_to_dict(exam)["questions"]}


@router.get("/history/mine")
def my_history(user: CurrentUser, db: DBSession) -> list[dict]:
    rows = db.scalars(select(Exam).where(Exam.user_id == user.id).order_by(Exam.id.desc())).all()
    out = []
    for e in rows:
        ch = db.get(Chapter, e.chapter_id)
        out.append({
            "id": e.id, "chapter_id": e.chapter_id,
            "chapter_title": ch.title if ch else "",
            "status": e.status,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "submitted_at": e.submitted_at.isoformat() if e.submitted_at else None,
        })
    return out


# ---- 教师端：考核配置 ----

class ExamConfigIn(BaseModel):
    chapter_id: int
    config: dict


@router.get("/config/{chapter_id}", dependencies=[Depends(require_role("teacher", "admin"))])
def get_config(chapter_id: int, db: DBSession) -> dict:
    cfg = db.scalar(select(ExamConfig).where(ExamConfig.chapter_id == chapter_id))
    if not cfg:
        return {"chapter_id": chapter_id, "config": {}}
    return {"chapter_id": chapter_id, "config": cfg.config_json}


@router.post("/config", dependencies=[Depends(require_role("teacher", "admin"))])
def upsert_config(payload: ExamConfigIn, db: DBSession) -> dict:
    if not db.get(Chapter, payload.chapter_id):
        raise HTTPException(404, "章节不存在")
    cfg = db.scalar(select(ExamConfig).where(ExamConfig.chapter_id == payload.chapter_id))
    if cfg:
        cfg.config_json = payload.config
    else:
        cfg = ExamConfig(chapter_id=payload.chapter_id, config_json=payload.config)
        db.add(cfg)
    db.commit()
    return {"ok": True}


# ---- 教师端：题库 ----

class QuestionIn(BaseModel):
    chapter_id: int
    kp_id: int | None = None
    type: str
    stem: str
    options: list[str] = []
    answer: str
    analysis: str = ""


@router.get("/bank", dependencies=[Depends(require_role("teacher", "admin"))])
def list_bank(db: DBSession, chapter_id: int | None = None) -> list[dict]:
    q = select(QuestionBank).order_by(QuestionBank.id.desc())
    if chapter_id:
        q = q.where(QuestionBank.chapter_id == chapter_id)
    rows = db.scalars(q).all()
    return [
        {
            "id": r.id, "chapter_id": r.chapter_id, "kp_id": r.kp_id,
            "type": r.type, "stem": r.stem, "options": r.options_json or [],
            "answer": r.answer, "analysis": r.analysis,
        }
        for r in rows
    ]


@router.post("/bank", dependencies=[Depends(require_role("teacher", "admin"))])
def add_bank(payload: QuestionIn, db: DBSession) -> dict:
    if not db.get(Chapter, payload.chapter_id):
        raise HTTPException(404, "章节不存在")
    q = QuestionBank(
        chapter_id=payload.chapter_id, kp_id=payload.kp_id, type=payload.type,
        stem=payload.stem, options_json=payload.options,
        answer=payload.answer, analysis=payload.analysis,
    )
    db.add(q); db.commit(); db.refresh(q)
    return {"id": q.id}


@router.put("/bank/{qid}", dependencies=[Depends(require_role("teacher", "admin"))])
def update_bank(qid: int, payload: QuestionIn, db: DBSession) -> dict:
    q = db.get(QuestionBank, qid)
    if not q:
        raise HTTPException(404, "题目不存在")
    q.chapter_id = payload.chapter_id
    q.kp_id = payload.kp_id
    q.type = payload.type
    q.stem = payload.stem
    q.options_json = payload.options
    q.answer = payload.answer
    q.analysis = payload.analysis
    db.commit()
    return {"ok": True}


@router.delete("/bank/{qid}", dependencies=[Depends(require_role("teacher", "admin"))])
def delete_bank(qid: int, db: DBSession) -> dict:
    q = db.get(QuestionBank, qid)
    if q:
        db.delete(q); db.commit()
    return {"ok": True}


@router.get("/knowledge-points/{chapter_id}")
def list_kps(chapter_id: int, _u: CurrentUser, db: DBSession) -> list[dict]:
    rows = db.scalars(select(KnowledgePoint).where(KnowledgePoint.chapter_id == chapter_id)).all()
    return [{"id": r.id, "name": r.name} for r in rows]


# ============ {exam_id} 通配路径（放最后） ============

class AnswerIn(BaseModel):
    idx: int
    answer: str


@router.post("/{exam_id}/answer")
def save_answer(exam_id: int, payload: AnswerIn, user: CurrentUser, db: DBSession) -> dict:
    exam = db.get(Exam, exam_id)
    if not exam or exam.user_id != user.id:
        raise HTTPException(404, "考核不存在")
    if exam.status == "submitted":
        raise HTTPException(400, "考核已提交")
    exam_service.save_answer(db, exam, payload.idx, payload.answer)
    return {"ok": True}


@router.post("/{exam_id}/submit")
def submit_exam(exam_id: int, user: CurrentUser, db: DBSession) -> dict:
    exam = db.get(Exam, exam_id)
    if not exam or exam.user_id != user.id:
        raise HTTPException(404, "考核不存在")
    if exam.status == "submitted":
        raise HTTPException(400, "考核已提交")
    exam = exam_service.grade_exam(db, exam)
    report = exam_service.generate_report(db, exam)
    return {"exam_id": exam.id, "report_id": report.id}


@router.get("/{exam_id}/report")
def get_report(exam_id: int, user: CurrentUser, db: DBSession) -> dict:
    exam = db.get(Exam, exam_id)
    if not exam or exam.user_id != user.id:
        raise HTTPException(404, "考核不存在")
    if exam.status != "submitted":
        raise HTTPException(400, "尚未提交")
    report = db.scalar(select(ExamReport).where(ExamReport.exam_id == exam_id))
    if not report:
        raise HTTPException(404, "报告尚未生成")
    return {
        "exam_id": exam_id,
        "chapter_id": exam.chapter_id,
        "dimensions": report.dimensions_json,
        "summary": report.summary,
        "suggestions": report.suggestions,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "questions": exam_service.exam_to_dict(exam)["questions"],
    }


@router.get("/{exam_id}")
def get_exam(exam_id: int, user: CurrentUser, db: DBSession) -> dict:
    exam = db.get(Exam, exam_id)
    if not exam or exam.user_id != user.id:
        raise HTTPException(404, "考核不存在")
    return exam_service.exam_to_dict(exam)
