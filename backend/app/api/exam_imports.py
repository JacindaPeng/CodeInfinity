"""往年考卷导入：上传解析、候选题审核、核实后入库。"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from ..config import settings
from ..deps import (
    CurrentUser,
    DBSession,
    assert_teacher_upload_class,
    require_role,
)
from ..models import Course, ExamImportFile, ExamImportJob, QuestionCandidate
from ..services.agent_access import (
    assert_teacher_can_manage_agent_content,
    get_teacher_agent_bound_classes,
    is_shared_agent_preview,
)
from ..services import exam_import_service

router = APIRouter(prefix="/exam-imports", tags=["exam-imports"])

ALLOWED_EXTS = {".pdf", ".doc", ".docx"}
MAX_FILE_BYTES = 20 * 1024 * 1024


def _import_dir(job_id: int) -> Path:
    d = Path(settings.upload_dir) / "exam_imports" / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _save_upload(dest_dir: Path, upload: UploadFile) -> tuple[str, str]:
    filename = upload.filename or "unknown"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"不支持的文件类型 {ext}，请上传 PDF / DOC / DOCX")
    raw = await upload.read()
    if not raw:
        raise HTTPException(400, f"文件为空：{filename}")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(400, f"文件过大（上限 {MAX_FILE_BYTES // 1024 // 1024}MB）：{filename}")
    safe = Path(filename).name.replace("..", "").replace("/", "_").replace("\\", "_")
    stored = f"{uuid.uuid4().hex[:12]}__{safe}"
    path = dest_dir / stored
    path.write_bytes(raw)
    return safe, str(path)


def _parse_class_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return list(dict.fromkeys(int(x) for x in data))
    except Exception:
        pass
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            continue
    return list(dict.fromkeys(out))


def _get_job_or_404(db: DBSession, job_id: int, user: CurrentUser) -> ExamImportJob:
    job = db.get(ExamImportJob, job_id)
    if not job:
        raise HTTPException(404, "导入任务不存在")
    if user.role != "admin" and job.created_by != user.id:
        # 同智能体管理者也可查看
        if job.agent_id:
            try:
                assert_teacher_can_manage_agent_content(db, user, job.agent_id)
            except HTTPException:
                raise HTTPException(403, "无权访问该导入任务")
        else:
            raise HTTPException(403, "无权访问该导入任务")
    return job


def _job_dict(job: ExamImportJob) -> dict:
    return {
        "id": job.id,
        "course_id": job.course_id,
        "agent_id": job.agent_id,
        "status": job.status,
        "progress": job.progress,
        "target_class_ids": job.target_class_ids_json or [],
        "settings": job.settings_json or {},
        "error_message": job.error_message or "",
        "stats": job.stats_json or {},
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "files": [
            {
                "id": f.id,
                "role": f.role,
                "filename": f.filename,
                "parse_status": f.parse_status,
                "extracted_chars": f.extracted_chars,
            }
            for f in (job.files or [])
        ],
    }


@router.post("", dependencies=[Depends(require_role("teacher", "admin"))])
async def create_import(
    user: CurrentUser,
    db: DBSession,
    course_id: int = Form(...),
    class_ids: str = Form(...),
    paper: UploadFile = File(...),
    answer: UploadFile | None = File(default=None),
    answers_in_paper: bool = Form(default=False),
    agent_id: int | None = Form(default=None),
) -> dict:
    """上传试卷与可选答案，后台拆题归类，完成后进入待审核。"""
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(404, "课程不存在")

    target_ids = _parse_class_ids(class_ids)
    if not target_ids:
        raise HTTPException(400, "请至少选择一个班级")
    for cid in target_ids:
        assert_teacher_upload_class(db, user, cid)

    resolved_agent_id = agent_id
    if agent_id is not None:
        agent = assert_teacher_can_manage_agent_content(db, user, agent_id)
        if is_shared_agent_preview(agent, user):
            raise HTTPException(403, "共享预览模式下不可导入题库")
        if user.role == "teacher" and agent.owner_id != user.id:
            allowed = set(get_teacher_agent_bound_classes(db, user, agent_id))
            for cid in target_ids:
                if cid not in allowed:
                    raise HTTPException(403, "该班级未绑定当前智能体")
        resolved_agent_id = agent_id

    job = ExamImportJob(
        course_id=course_id,
        agent_id=resolved_agent_id,
        created_by=user.id,
        status="uploaded",
        progress=0,
        target_class_ids_json=target_ids,
        settings_json={
            "answers_in_paper": bool(answers_in_paper),
            "course_name": course.name,
            "paper_name": paper.filename or "",
            "answer_name": (answer.filename if answer and answer.filename else ""),
        },
    )
    db.add(job)
    db.flush()

    dest = _import_dir(job.id)
    paper_name, paper_path = await _save_upload(dest, paper)
    db.add(ExamImportFile(
        job_id=job.id, role="paper", filename=paper_name, file_path=paper_path,
    ))
    if answer is not None and answer.filename:
        ans_name, ans_path = await _save_upload(dest, answer)
        db.add(ExamImportFile(
            job_id=job.id, role="answer", filename=ans_name, file_path=ans_path,
        ))
    elif not answers_in_paper:
        # 无答案：后续由 AI 生成
        pass

    db.commit()
    exam_import_service.start_import_job_async(job.id)
    return {"id": job.id, "status": "parsing", "message": "已开始解析，请稍候刷新状态"}


@router.get("", dependencies=[Depends(require_role("teacher", "admin"))])
def list_imports(
    user: CurrentUser,
    db: DBSession,
    course_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
) -> list[dict]:
    q = select(ExamImportJob).order_by(ExamImportJob.id.desc())
    if user.role != "admin":
        q = q.where(ExamImportJob.created_by == user.id)
    if course_id is not None:
        q = q.where(ExamImportJob.course_id == course_id)
    if agent_id is not None:
        q = q.where(ExamImportJob.agent_id == agent_id)
    rows = db.scalars(q.limit(50)).all()
    return [_job_dict(r) for r in rows]


@router.get("/{job_id}", dependencies=[Depends(require_role("teacher", "admin"))])
def get_import(job_id: int, user: CurrentUser, db: DBSession) -> dict:
    job = _get_job_or_404(db, job_id, user)
    data = _job_dict(job)
    data["candidate_count"] = len(job.candidates or [])
    data["approved_count"] = sum(1 for c in (job.candidates or []) if c.status == "approved")
    data["pending_count"] = sum(1 for c in (job.candidates or []) if c.status == "pending")
    return data


@router.get("/{job_id}/candidates", dependencies=[Depends(require_role("teacher", "admin"))])
def list_candidates(
    job_id: int,
    user: CurrentUser,
    db: DBSession,
    status: str | None = Query(default=None),
) -> list[dict]:
    job = _get_job_or_404(db, job_id, user)
    rows = list(job.candidates or [])
    if status:
        rows = [c for c in rows if c.status == status]
    rows.sort(key=lambda c: c.id)
    return [exam_import_service.candidate_to_dict(c) for c in rows]


class CandidateUpdateIn(BaseModel):
    type: str | None = None
    stem: str | None = None
    options: list[str] | None = None
    answer: str | None = None
    analysis: str | None = None
    chapter_id: int | None = None
    extra_chapter_ids: list[int] | None = None
    kp_id: int | None = None
    new_kp_name: str | None = None
    extra_kp_names: list[str] | None = None
    status: str | None = None
    review_note: str | None = None


@router.put("/{job_id}/candidates/{cid}", dependencies=[Depends(require_role("teacher", "admin"))])
def update_candidate(
    job_id: int,
    cid: int,
    payload: CandidateUpdateIn,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    job = _get_job_or_404(db, job_id, user)
    if job.status not in ("reviewing", "completed", "failed"):
        # classifying 中也可编辑，但通常等 reviewing
        if job.status not in ("parsing", "classifying", "uploaded"):
            pass
    cand = db.get(QuestionCandidate, cid)
    if not cand or cand.job_id != job.id:
        raise HTTPException(404, "候选题不存在")

    data = payload.model_dump(exclude_unset=True)
    if "options" in data:
        cand.options_json = data.pop("options") or []
    if "extra_chapter_ids" in data:
        cand.extra_chapter_ids_json = data.pop("extra_chapter_ids") or []
    if "extra_kp_names" in data:
        cand.extra_kp_names_json = [
            str(x).strip() for x in (data.pop("extra_kp_names") or []) if str(x).strip()
        ]
    if "status" in data and data["status"] is not None:
        if data["status"] not in ("pending", "approved", "rejected"):
            raise HTTPException(400, "无效状态")
        cand.status = data.pop("status")
    if "answer" in data and data["answer"] is not None:
        cand.answer = data.pop("answer")
        cand.answer_source = "manual"
    if "stem" in data and data["stem"] is not None:
        cand.stem = data.pop("stem")
        cand.content_hash = exam_import_service.stem_hash(cand.stem)
    for key in (
        "type", "analysis", "chapter_id", "kp_id", "new_kp_name", "review_note",
    ):
        if key in data and data[key] is not None:
            setattr(cand, key, data[key])
    db.commit()
    return exam_import_service.candidate_to_dict(cand)


class BulkReviewIn(BaseModel):
    candidate_ids: list[int] = []
    status: str  # approved / rejected / pending
    all_pending: bool = False


@router.post("/{job_id}/candidates/bulk-review", dependencies=[Depends(require_role("teacher", "admin"))])
def bulk_review(
    job_id: int,
    payload: BulkReviewIn,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    job = _get_job_or_404(db, job_id, user)
    if payload.status not in ("approved", "rejected", "pending"):
        raise HTTPException(400, "无效状态")
    updated = 0
    for c in job.candidates or []:
        if payload.all_pending and c.status == "pending":
            c.status = payload.status
            updated += 1
        elif c.id in payload.candidate_ids:
            c.status = payload.status
            updated += 1
    db.commit()
    return {"ok": True, "updated": updated}


@router.post("/{job_id}/publish", dependencies=[Depends(require_role("teacher", "admin"))])
def publish_import(
    job_id: int,
    user: CurrentUser,
    db: DBSession,
    only_approved: bool = Query(default=True),
) -> dict:
    job = _get_job_or_404(db, job_id, user)
    for cid in job.target_class_ids_json or []:
        assert_teacher_upload_class(db, user, int(cid))
    if job.agent_id:
        assert_teacher_can_manage_agent_content(db, user, job.agent_id)
    try:
        return exam_import_service.publish_job(db, job, only_approved=only_approved)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{job_id}/retry", dependencies=[Depends(require_role("teacher", "admin"))])
def retry_import(job_id: int, user: CurrentUser, db: DBSession) -> dict:
    job = _get_job_or_404(db, job_id, user)
    if job.status not in ("failed", "reviewing"):
        raise HTTPException(400, "仅失败或待审核任务可重新解析")
    job.status = "uploaded"
    job.progress = 0
    job.error_message = ""
    db.commit()
    exam_import_service.start_import_job_async(job.id)
    return {"ok": True, "id": job.id, "status": "parsing"}
