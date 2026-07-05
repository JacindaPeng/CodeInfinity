"""资料管理：教师上传、列表、删除、重建索引、统计。"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import select

from ..config import settings
from ..deps import CurrentUser, DBSession, require_role
from ..models import Chapter, Material
from ..services import indexer, vector_store
from ..services.indexer import index_material

router = APIRouter(prefix="/materials", tags=["materials"])

ALLOWED = {".pdf", ".ppt", ".pptx", ".doc", ".docx", ".txt", ".mp4", ".mov", ".avi", ".mkv"}
EXT_TO_TYPE = {
    ".pdf": "pdf", ".ppt": "ppt", ".pptx": "ppt",
    ".doc": "word", ".docx": "word", ".txt": "word",
    ".mp4": "video", ".mov": "video", ".avi": "video", ".mkv": "video",
}


def _save_upload(file: UploadFile) -> str:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"不支持的文件类型: {ext}")
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    safe_name = f"{int(__import__('time').time())}_{Path(file.filename).name}"
    dest = Path(settings.upload_dir) / safe_name
    with dest.open("wb") as f:
        f.write(file.file.read())
    return str(dest.resolve())


@router.get("")
def list_materials(_u: CurrentUser, db: DBSession, chapter_id: int | None = None) -> list[dict]:
    q = select(Material).order_by(Material.id.desc())
    if chapter_id:
        q = q.where(Material.chapter_id == chapter_id)
    rows = db.scalars(q).all()
    return [
        {
            "id": m.id, "chapter_id": m.chapter_id, "type": m.type,
            "title": m.title, "file_path": m.file_path, "file_name": Path(m.file_path).name,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


@router.post("/upload", dependencies=[Depends(require_role("teacher", "admin"))])
def upload(
    db: DBSession,
    chapter_id: int = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    if not db.get(Chapter, chapter_id):
        raise HTTPException(404, "章节不存在")
    path = _save_upload(file)
    ext = Path(file.filename or "").suffix.lower()
    material = Material(
        chapter_id=chapter_id, type=EXT_TO_TYPE[ext],
        title=title, file_path=path,
    )
    db.add(material); db.commit(); db.refresh(material)

    # 异步转写/解析大文件会阻塞，这里同步执行；生产可改 Celery
    try:
        chunks = index_material(db, material)
        return {"ok": True, "material_id": material.id, "chunks": chunks}
    except Exception as e:
        return {"ok": True, "material_id": material.id, "chunks": 0, "warning": f"索引失败: {e}"}


@router.delete("/{material_id}", dependencies=[Depends(require_role("teacher", "admin"))])
def delete_material(material_id: int, db: DBSession) -> dict:
    m = db.get(Material, material_id)
    if not m:
        raise HTTPException(404, "资料不存在")
    try:
        if os.path.exists(m.file_path):
            os.unlink(m.file_path)
    except OSError:
        pass
    vector_store.delete_by_material(material_id)
    db.delete(m); db.commit()
    return {"ok": True}


@router.post("/reindex", dependencies=[Depends(require_role("teacher", "admin"))])
def reindex(db: DBSession) -> dict:
    return indexer.reindex_all(db)


@router.get("/stats")
def stats(_u: CurrentUser) -> dict:
    return {"chunks": vector_store.count()}


@router.get("/file/{material_id}")
def get_file(material_id: int, db: DBSession) -> FileResponse:
    """供前端预览/播放原始文件（视频/PDF 等）。"""
    m = db.get(Material, material_id)
    if not m or not os.path.exists(m.file_path):
        raise HTTPException(404, "文件不存在")
    return FileResponse(m.file_path, filename=Path(m.file_path).name)
