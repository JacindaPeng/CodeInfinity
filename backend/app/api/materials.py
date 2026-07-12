"""资料管理：教师上传、列表、删除、重建索引、统计、整本教材拆分上传。"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from sqlalchemy import select

from ..config import settings
from ..deps import (
    CurrentUser,
    DBSession,
    assert_can_access_material,
    assert_teacher_upload_class,
    require_role,
    resolve_resource_class_ids,
)
from ..models import Chapter, Material
from ..services import indexer, vector_store
from ..services.chapter_splitter import detect_chapters_in_pdf, split_pdf_by_chapters
from ..services.indexer import index_material, index_pdf_pages, _build_page_offset_map

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
def list_materials(
    user: CurrentUser,
    db: DBSession,
    chapter_id: int | None = None,
    class_id: int | None = Query(default=None),
) -> list[dict]:
    allowed_classes = resolve_resource_class_ids(db, user, class_id)
    q = select(Material).order_by(Material.id.desc())
    if chapter_id:
        q = q.where(Material.chapter_id == chapter_id)
    if allowed_classes is not None:
        if not allowed_classes:
            return []
        q = q.where(Material.class_id.in_(allowed_classes))
    rows = db.scalars(q).all()
    return [
        {
            "id": m.id, "chapter_id": m.chapter_id, "class_id": m.class_id,
            "type": m.type,
            "title": m.title, "file_path": m.file_path, "file_name": Path(m.file_path).name,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


@router.post("/upload", dependencies=[Depends(require_role("teacher", "admin"))])
def upload(
    user: CurrentUser,
    db: DBSession,
    chapter_id: int = Form(...),
    class_ids: list[int] = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    if not db.get(Chapter, chapter_id):
        raise HTTPException(404, "章节不存在")
    unique_class_ids = list(dict.fromkeys(class_ids))
    if not unique_class_ids:
        raise HTTPException(400, "请至少选择一个班级")
    for cid in unique_class_ids:
        assert_teacher_upload_class(db, user, cid)

    path = _save_upload(file)
    ext = Path(file.filename or "").suffix.lower()
    material_ids: list[int] = []
    total_chunks = 0
    warning = None

    for cid in unique_class_ids:
        material = Material(
            chapter_id=chapter_id, class_id=cid, type=EXT_TO_TYPE[ext],
            title=title, file_path=path,
        )
        db.add(material)
        db.flush()
        try:
            chunks = index_material(db, material)
            total_chunks += chunks
            material_ids.append(material.id)
            if ext == ".pdf" and warning is None:
                import pdfplumber
                with pdfplumber.open(path) as pdf:
                    pages = [p.extract_text() or "" for p in pdf.pages]
                detected = detect_chapters_in_pdf(pages)
                if len(detected) > 1:
                    warning = f"检测到该 PDF 含 {len(detected)} 个章节标题，建议改用「整本教材上传」以正确归属章节。"
        except Exception as e:
            raise HTTPException(500, f"索引失败: {e}")

    db.commit()
    return {
        "ok": True,
        "material_ids": material_ids,
        "material_id": material_ids[0] if material_ids else None,
        "chunks": total_chunks,
        "class_count": len(unique_class_ids),
        "warning": warning,
    }


@router.post("/upload-textbook", dependencies=[Depends(require_role("teacher", "admin"))])
def upload_textbook(
    user: CurrentUser,
    db: DBSession,
    class_ids: list[int] = Form(...),
    file: UploadFile = File(...),
    title_prefix: str = Form(""),
) -> dict:
    """整本教材 PDF 上传：自动按章节拆分，每章创建独立 Material 并索引对应页面。"""
    unique_class_ids = list(dict.fromkeys(class_ids))
    if not unique_class_ids:
        raise HTTPException(400, "请至少选择一个班级")
    for cid in unique_class_ids:
        assert_teacher_upload_class(db, user, cid)
    ext = Path(file.filename or "").suffix.lower()
    if ext != ".pdf":
        raise HTTPException(400, "整本教材上传仅支持 PDF")
    path = _save_upload(file)

    import pdfplumber
    with pdfplumber.open(path) as pdf:
        pages_text = [p.extract_text() or "" for p in pdf.pages]

    # 从 DB 取章节列表
    chapters = db.scalars(select(Chapter).order_by(Chapter.order_idx)).all()
    chapter_dicts = [{"id": c.id, "title": c.title, "order_idx": c.order_idx} for c in chapters]

    # 切分
    splits = split_pdf_by_chapters(pages_text, chapter_dicts)
    if not splits:
        raise HTTPException(400, "未能识别 PDF 中的章节标题，请确认 PDF 包含「第N章」格式的章节标题。")

    # 构建印刷页码映射
    offset_map = _build_page_offset_map(pages_text, splits)

    prefix = title_prefix or Path(file.filename).stem
    results = []
    total_chunks = 0
    for cid in unique_class_ids:
        for sp in splits:
            material = Material(
                chapter_id=sp["chapter_id"],
                class_id=cid,
                type="pdf",
                title=f"{prefix} - {sp['chapter_title']}",
                file_path=path,
                meta_json={"page_start": sp["start_page"], "page_end": sp["end_page"]},
            )
            db.add(material); db.flush()
            chunks = index_pdf_pages(
                db, material, pages_text, (sp["start_page"], sp["end_page"]), offset_map=offset_map
            )
            total_chunks += chunks
            results.append({
                "class_id": cid,
                "chapter_id": sp["chapter_id"],
                "chapter_title": sp["chapter_title"],
                "page_range": f"{sp['start_page']}-{sp['end_page']}",
                "material_id": material.id,
                "chunks": chunks,
            })
    db.commit()

    return {
        "ok": True,
        "total_pages": len(pages_text),
        "chapters_split": len(splits),
        "class_count": len(unique_class_ids),
        "total_chunks": total_chunks,
        "details": results,
    }


@router.delete("/{material_id}", dependencies=[Depends(require_role("teacher", "admin"))])
def delete_material(material_id: int, user: CurrentUser, db: DBSession) -> dict:
    m = db.get(Material, material_id)
    if not m:
        raise HTTPException(404, "资料不存在")
    assert_can_access_material(db, user, m)
    # 整本教材共享文件：仅当无其他 material 引用时才删除物理文件
    other_refs = db.scalar(select(Material).where(
        Material.file_path == m.file_path, Material.id != m.id
    ))
    if not other_refs:
        try:
            if os.path.exists(m.file_path):
                os.unlink(m.file_path)
        except OSError:
            pass
    vector_store.delete_by_material(material_id)
    db.delete(m); db.commit()
    return {"ok": True}


@router.post("/reindex", dependencies=[Depends(require_role("teacher", "admin"))])
def reindex(user: CurrentUser, db: DBSession) -> dict:
    allowed = resolve_resource_class_ids(db, user)
    return indexer.reindex_all(db, class_ids=allowed)


@router.post("/re-split-textbook", dependencies=[Depends(require_role("teacher", "admin"))])
def re_split_textbook(user: CurrentUser, db: DBSession) -> dict:
    """重新拆分已上传的整本教材：删除旧资料，清空 Chroma 向量库，
    用新的章节拆分逻辑重新创建资料并全量重建索引。
    """
    allowed_classes = resolve_resource_class_ids(db, user)
    # 找到所有共享 file_path 的 PDF 资料组
    file_paths = db.scalars(
        select(Material.file_path).where(Material.type == "pdf").distinct()
    ).all()

    textbook_file_paths = []  # 记录哪些文件是整本教材
    total_deleted = 0

    for fp in file_paths:
        if not os.path.exists(fp):
            continue
        materials = db.scalars(
            select(Material).where(Material.file_path == fp, Material.type == "pdf")
        ).all()
        if allowed_classes is not None:
            materials = [m for m in materials if m.class_id in allowed_classes]
        if len(materials) < 3:
            continue
        textbook_file_paths.append((fp, materials))
        total_deleted += len(materials)

    if not textbook_file_paths:
        raise HTTPException(400, "未找到整本教材上传的资料（需≥3个PDF资料共享同一文件）。请先通过「整本教材上传」上传教材。")

    # 1. 删除旧教材资料的向量（教师仅影响所管班级，管理员清空全库）
    if allowed_classes is None:
        vector_store.reset_collection()
    else:
        for _, materials in textbook_file_paths:
            for m in materials:
                vector_store.delete_by_material(m.id)

    # 2. 删除所有旧教材资料
    for fp, materials in textbook_file_paths:
        for m in materials:
            db.delete(m)
    db.flush()

    # 3. 用新拆分逻辑重新创建资料并索引
    chapters = db.scalars(select(Chapter).order_by(Chapter.order_idx)).all()
    chapter_dicts = [{"id": c.id, "title": c.title, "order_idx": c.order_idx} for c in chapters]

    total_created = 0
    total_chunks = 0
    results = []

    for fp, orig_materials in textbook_file_paths:
        try:
            import pdfplumber
            with pdfplumber.open(fp) as pdf:
                pages_text = [p.extract_text() or "" for p in pdf.pages]
        except Exception as e:
            results.append({"error": f"读取PDF失败: {e}"})
            continue

        splits = split_pdf_by_chapters(pages_text, chapter_dicts)
        if not splits:
            results.append({"error": "未能识别章节标题"})
            continue

        # 构建印刷页码映射
        offset_map = _build_page_offset_map(pages_text, splits)

        prefix = Path(fp).stem
        class_id = orig_materials[0].class_id if orig_materials else None
        for sp in splits:
            new_m = Material(
                chapter_id=sp["chapter_id"],
                class_id=class_id,
                type="pdf",
                title=f"{prefix} - {sp['chapter_title']}",
                file_path=fp,
                meta_json={"page_start": sp["start_page"], "page_end": sp["end_page"]},
            )
            db.add(new_m); db.flush()
            chunks = index_pdf_pages(db, new_m, pages_text, (sp["start_page"], sp["end_page"]), offset_map=offset_map)
            total_chunks += chunks
            total_created += 1
            results.append({
                "chapter_title": sp["chapter_title"],
                "page_range": f"{sp['start_page']}-{sp['end_page']}",
                "chunks": chunks,
            })

    # 4. 管理员全量重建后，对非教材的其他资料也重新索引
    if allowed_classes is None:
        other_materials = db.scalars(
            select(Material).where(Material.type != "pdf")
        ).all()
    else:
        other_materials = []
    from ..services.indexer import index_material
    for m in other_materials:
        try:
            index_material(db, m)
        except Exception as e:
            print(f"[re-split] re-index material {m.id} failed: {e}")

    db.commit()
    return {
        "ok": True,
        "deleted_old": total_deleted,
        "materials_created": total_created,
        "total_chunks": total_chunks,
        "details": results,
    }


@router.get("/stats")
def stats(user: CurrentUser, db: DBSession) -> dict:
    allowed = resolve_resource_class_ids(db, user)
    return {"chunks": vector_store.count(class_ids=allowed)}


@router.get("/file/{material_id}")
def get_file(material_id: int, user: CurrentUser, db: DBSession) -> FileResponse:
    m = db.get(Material, material_id)
    if not m or not os.path.exists(m.file_path):
        raise HTTPException(404, "文件不存在")
    assert_can_access_material(db, user, m)
    return FileResponse(m.file_path, filename=Path(m.file_path).name)
