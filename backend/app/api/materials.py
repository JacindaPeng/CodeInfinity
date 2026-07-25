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
from ..models import Agent, Chapter, Course, Material
from ..services import indexer, vector_store
from ..services.agent_access import (
    assert_teacher_can_manage_agent_content,
    apply_agent_content_scope,
    get_teacher_agent_bound_classes,
    resolve_resource_class_ids_for_agent,
)
from ..services.chapter_splitter import detect_chapters_in_pdf, split_pdf_by_chapters, build_chapter_plan_from_courseware, extract_pdf_pages_with_corners
from ..services.chapter_sync import (
    resolve_chapters_for_textbook,
    C_LANG_COURSE_ID,
    assert_teacher_can_manage_course,
    create_custom_chapters,
    requires_agent_scoped_chapters,
    uses_course_level_preset_chapters,
)
from ..services.indexer import index_material, index_pdf_pages, _build_page_offset_map
from ..services.storage_paths import portable_upload_path, resolve_upload_path, stored_filename

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
    safe_name = f"{int(__import__('time').time())}_{Path(file.filename or 'file').name}"
    dest = Path(settings.upload_dir) / safe_name
    with dest.open("wb") as f:
        f.write(file.file.read())
    # 写入当前 UPLOAD_DIR 下的绝对路径，读取时再用 resolve_upload_path 兼容跨环境
    return portable_upload_path(safe_name)


@router.get("")
def list_materials(
    user: CurrentUser,
    db: DBSession,
    chapter_id: int | None = None,
    class_id: int | None = Query(default=None),
    course_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
) -> list[dict]:
    agent = db.get(Agent, agent_id) if agent_id else None
    if agent and user.role == "teacher" and agent.owner_id == user.id:
        from ..services.agent_adopt import dedupe_agent_content, repair_adopted_chapter_links

        changed = bool(repair_adopted_chapter_links(db, agent))
        if dedupe_agent_content(db, agent):
            changed = True
        if changed:
            db.commit()
            db.refresh(agent)

    allowed_classes = resolve_resource_class_ids_for_agent(
        db, user, class_id, agent_id=agent_id,
    )
    q = select(Material).order_by(Material.id.desc())
    if chapter_id:
        q = q.where(Material.chapter_id == chapter_id)
    if course_id is not None:
        ch_q = select(Chapter.id).where(Chapter.course_id == course_id)
        if uses_course_level_preset_chapters(db, course_id, agent_id):
            ch_q = ch_q.where(Chapter.agent_id.is_(None))
        elif requires_agent_scoped_chapters(db, course_id, agent_id):
            if agent_id is None:
                return []
            ch_q = ch_q.where(Chapter.agent_id == agent_id)
        chapter_ids = db.scalars(ch_q).all()
        if not chapter_ids:
            return []
        q = q.where(Material.chapter_id.in_(chapter_ids))
    q = apply_agent_content_scope(Material, q, agent, allowed_classes, db=db)
    if q is None:
        return []
    rows = db.scalars(q).all()
    return [
        {
            "id": m.id, "chapter_id": m.chapter_id, "class_id": m.class_id,
            "type": m.type,
            "title": m.title, "file_path": m.file_path, "file_name": stored_filename(m.file_path),
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


def _resolve_upload_agent_id(
    db: DBSession,
    user: CurrentUser,
    agent_id: int | None,
    class_ids: list[int] | None = None,
) -> int | None:
    if agent_id is None:
        return None
    agent = assert_teacher_can_manage_agent_content(db, user, agent_id)
    if user.role == "teacher" and agent.owner_id != user.id and class_ids:
        allowed = set(get_teacher_agent_bound_classes(db, user, agent_id))
        for cid in class_ids:
            if cid not in allowed:
                raise HTTPException(403, "该班级未绑定当前智能体")
    return agent_id


@router.post("/upload", dependencies=[Depends(require_role("teacher", "admin"))])
def upload(
    user: CurrentUser,
    db: DBSession,
    chapter_id: int = Form(...),
    class_ids: list[int] = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    agent_id: int | None = Form(default=None),
) -> dict:
    if not db.get(Chapter, chapter_id):
        raise HTTPException(404, "章节不存在")
    unique_class_ids = list(dict.fromkeys(class_ids))
    if not unique_class_ids:
        raise HTTPException(400, "请至少选择一个班级")
    for cid in unique_class_ids:
        assert_teacher_upload_class(db, user, cid)

    resolved_agent_id = _resolve_upload_agent_id(db, user, agent_id, unique_class_ids)
    path = _save_upload(file)
    ext = Path(file.filename or "").suffix.lower()
    material_ids: list[int] = []
    total_chunks = 0
    warning = None

    for cid in unique_class_ids:
        material = Material(
            chapter_id=chapter_id, class_id=cid, type=EXT_TO_TYPE[ext],
            title=title, file_path=path, agent_id=resolved_agent_id,
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
    course_id: int = Form(...),
    class_ids: list[int] = Form(...),
    file: UploadFile = File(...),
    title_prefix: str = Form(""),
    agent_id: int | None = Form(default=None),
    toc_page_start: int | None = Form(default=None),
    toc_page_end: int | None = Form(default=None),
) -> dict:
    """整本教材 PDF 上传：按课程拆分章节。无预置章节的课程（如 Java）会从 PDF 自动创建章节。"""
    if not db.get(Course, course_id):
        raise HTTPException(404, "课程不存在")
    unique_class_ids = list(dict.fromkeys(class_ids))
    if not unique_class_ids:
        raise HTTPException(400, "请至少选择一个班级")
    for cid in unique_class_ids:
        assert_teacher_upload_class(db, user, cid)
    resolved_agent_id = _resolve_upload_agent_id(db, user, agent_id, unique_class_ids)
    ext = Path(file.filename or "").suffix.lower()
    if ext != ".pdf":
        raise HTTPException(400, "整本教材上传仅支持 PDF")

    if toc_page_start is not None and toc_page_start < 1:
        raise HTTPException(400, "目录起始页须 ≥ 1（PDF 阅读器页码）")
    if toc_page_end is not None and toc_page_end < 1:
        raise HTTPException(400, "目录结束页须 ≥ 1（PDF 阅读器页码）")
    if (
        toc_page_start is not None
        and toc_page_end is not None
        and toc_page_end < toc_page_start
    ):
        raise HTTPException(400, "目录结束页不能小于起始页")

    path = _save_upload(file)

    pages_text, page_corners = extract_pdf_pages_with_corners(path)

    chapter_dicts, chapters_created = resolve_chapters_for_textbook(
        db,
        course_id,
        pages_text,
        agent_id=resolved_agent_id,
        page_corners=page_corners,
        toc_page_start=toc_page_start,
        toc_page_end=toc_page_end,
    )

    splits = split_pdf_by_chapters(
        pages_text, chapter_dicts,
        dynamic_course=requires_agent_scoped_chapters(db, course_id, resolved_agent_id),
        page_corners=page_corners,
    )
    if not splits:
        raise HTTPException(400, "未能识别 PDF 中的章节标题，请确认 PDF 包含「第N章」格式的章节标题。")

    offset_map = _build_page_offset_map(pages_text, splits)

    prefix = title_prefix or Path(file.filename).stem
    results = []
    total_chunks = 0
    index_errors: list[str] = []
    # 先落库章节与资料元数据，再索引；避免 Chroma/ONNX 下载卡住导致整单回滚「看起来没生成章节」
    material_jobs: list[tuple[Material, tuple[int, int], dict]] = []
    for cid in unique_class_ids:
        for sp in splits:
            material = Material(
                chapter_id=sp["chapter_id"],
                class_id=cid,
                type="pdf",
                title=f"{prefix} - {sp['chapter_title']}",
                file_path=path,
                agent_id=resolved_agent_id,
                meta_json={"page_start": sp["start_page"], "page_end": sp["end_page"]},
            )
            db.add(material)
            db.flush()
            detail = {
                "class_id": cid,
                "chapter_id": sp["chapter_id"],
                "chapter_title": sp["chapter_title"],
                "page_range": f"{sp['start_page']}-{sp['end_page']}",
                "material_id": material.id,
                "chunks": 0,
            }
            results.append(detail)
            material_jobs.append(
                (material, (sp["start_page"], sp["end_page"]), detail)
            )

    from ..services.agent_service import maybe_activate_course_agent
    maybe_activate_course_agent(db, course_id)
    db.commit()

    for material, page_range, detail in material_jobs:
        try:
            chunks = index_pdf_pages(
                db, material, pages_text, page_range, offset_map=offset_map
            )
            detail["chunks"] = chunks
            total_chunks += chunks
        except Exception as e:
            msg = f"{detail.get('chapter_title')}: {e}"
            index_errors.append(msg)
            detail["index_error"] = str(e)

    out = {
        "ok": True,
        "course_id": course_id,
        "chapters_created": chapters_created,
        "total_pages": len(pages_text),
        "chapters_split": len(splits),
        "class_count": len(unique_class_ids),
        "total_chunks": total_chunks,
        "details": results,
    }
    if index_errors:
        out["warning"] = (
            "章节已生成，但向量索引未完成（常见于 Docker 首次下载 Chroma ONNX 模型过慢）。"
            "请稍后点击「重建索引」，或确认容器已预热 embedding 模型。"
        )
        out["index_errors"] = index_errors[:8]
    return out


@router.post("/upload-courseware-batch", dependencies=[Depends(require_role("teacher", "admin"))])
def upload_courseware_batch(
    user: CurrentUser,
    db: DBSession,
    course_id: int = Form(...),
    class_ids: list[int] = Form(...),
    files: list[UploadFile] = File(...),
    agent_id: int | None = Form(default=None),
) -> dict:
    """批量上传各章课件：从文件名/PDF 首页识别章节并创建结构，同时索引资料。"""
    if not db.get(Course, course_id):
        raise HTTPException(404, "课程不存在")
    unique_class_ids = list(dict.fromkeys(class_ids))
    if not unique_class_ids:
        raise HTTPException(400, "请至少选择一个班级")
    for cid in unique_class_ids:
        assert_teacher_upload_class(db, user, cid)

    resolved_agent_id = _resolve_upload_agent_id(db, user, agent_id, unique_class_ids)
    if uses_course_level_preset_chapters(db, course_id, resolved_agent_id):
        raise HTTPException(400, "C 语言原智能体使用预置章节，请使用单章上传")
    assert_teacher_can_manage_course(db, user, course_id)

    if not files:
        raise HTTPException(400, "请至少选择一个课件文件")
    if len(files) > 50:
        raise HTTPException(400, "单次最多上传 50 个课件")

    existing = db.scalars(
        select(Chapter.id).where(
            Chapter.course_id == course_id,
            Chapter.agent_id == resolved_agent_id,
        ).limit(1)
    ).first()
    if existing:
        raise HTTPException(400, "该智能体下已有章节，请使用「单章上传」补充资料")

    filenames = [f.filename or f"file{i}" for i, f in enumerate(files)]

    saved_paths: list[str] = []
    file_paths: dict[int, str] = {}
    try:
        for i, uf in enumerate(files):
            path = _save_upload(uf)
            saved_paths.append(path)
            file_paths[i] = path

        try:
            plan = build_chapter_plan_from_courseware(filenames, file_paths=file_paths)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

        chapter_rows = create_custom_chapters(
            db,
            course_id,
            [{"order_idx": p["order_idx"], "title": p["title"], "description": p.get("description") or ""} for p in plan],
            agent_id=resolved_agent_id,
            commit=False,
        )
        order_to_id = {c["order_idx"]: c["id"] for c in chapter_rows}

        results = []
        total_chunks = 0
        index_errors: list[str] = []
        index_jobs: list[tuple[Material, str]] = []
        for item in plan:
            file_idx = item["file_index"]
            path = saved_paths[file_idx]
            uf = files[file_idx]
            ext = Path(uf.filename or "").suffix.lower()
            if ext not in EXT_TO_TYPE:
                raise HTTPException(400, f"不支持的文件类型: {ext}")
            chapter_id = order_to_id[item["order_idx"]]
            title = item["title"]
            material_ids: list[int] = []
            for cid in unique_class_ids:
                material = Material(
                    chapter_id=chapter_id,
                    class_id=cid,
                    type=EXT_TO_TYPE[ext],
                    title=title,
                    file_path=path,
                    agent_id=resolved_agent_id,
                )
                db.add(material)
                db.flush()
                material_ids.append(material.id)
                index_jobs.append((material, uf.filename or title))
            results.append({
                "chapter_id": chapter_id,
                "chapter_title": item["title"],
                "file_name": uf.filename,
                "parse_source": item["parse_source"],
                "material_ids": material_ids,
                "chunks": 0,
            })

        from ..services.agent_service import maybe_activate_course_agent
        maybe_activate_course_agent(db, course_id)
        # 先提交章节结构，避免索引阶段失败导致「章节未生成」
        db.commit()

        chunks_by_material: dict[int, int] = {}
        for material, fname in index_jobs:
            try:
                chunks_by_material[material.id] = index_material(db, material)
                total_chunks += chunks_by_material[material.id]
            except Exception as e:
                index_errors.append(f"{fname}: {e}")
                chunks_by_material[material.id] = 0
        for row in results:
            row["chunks"] = sum(chunks_by_material.get(mid, 0) for mid in row["material_ids"])
    except Exception:
        db.rollback()
        for path in saved_paths:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError:
                pass
        raise

    out = {
        "ok": True,
        "course_id": course_id,
        "chapters_created": len(chapter_rows),
        "class_count": len(unique_class_ids),
        "total_chunks": total_chunks,
        "details": results,
    }
    if index_errors:
        out["warning"] = (
            "章节已生成，但部分资料索引失败（Docker 首次下载 embedding 模型过慢时常见）。"
            "可稍后点击「重建索引」。"
        )
        out["index_errors"] = index_errors[:8]
    return out


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
            resolved = resolve_upload_path(m.file_path)
            if resolved is not None:
                resolved.unlink()
        except OSError:
            pass
    vector_store.delete_by_material(material_id)
    db.delete(m); db.commit()
    return {"ok": True}


@router.post("/reindex", dependencies=[Depends(require_role("teacher", "admin"))])
def reindex(user: CurrentUser, db: DBSession) -> dict:
    allowed = resolve_resource_class_ids(db, user)
    return indexer.reindex_all(db, class_ids=allowed)


@router.post("/reindex-videos", dependencies=[Depends(require_role("teacher", "admin"))])
def reindex_videos_api(user: CurrentUser, db: DBSession) -> dict:
    """仅重建视频（换 Whisper 模型后用；不动 PDF）。"""
    allowed = resolve_resource_class_ids(db, user)
    return indexer.reindex_videos(db, class_ids=allowed)


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
        if resolve_upload_path(fp) is None:
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

    # 3. 用新拆分逻辑重新创建资料并索引（按教材所属课程过滤章节）
    total_created = 0
    total_chunks = 0
    results = []

    for fp, orig_materials in textbook_file_paths:
        try:
            disk = resolve_upload_path(fp)
            if disk is None:
                results.append({"error": f"文件不存在: {stored_filename(fp)}"})
                continue
            pages_text, page_corners = extract_pdf_pages_with_corners(str(disk))
        except Exception as e:
            results.append({"error": f"读取PDF失败: {e}"})
            continue

        sample_ch = db.get(Chapter, orig_materials[0].chapter_id) if orig_materials else None
        course_id = sample_ch.course_id if sample_ch else None
        if not course_id:
            results.append({"error": "无法确定教材所属课程"})
            continue

        chapters = db.scalars(
            select(Chapter).where(Chapter.course_id == course_id).order_by(Chapter.order_idx)
        ).all()
        chapter_dicts = [{"id": c.id, "title": c.title, "order_idx": c.order_idx} for c in chapters]

        splits = split_pdf_by_chapters(
            pages_text, chapter_dicts,
            dynamic_course=requires_agent_scoped_chapters(db, course_id, None),
            page_corners=page_corners,
        )
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
    path = resolve_upload_path(m.file_path) if m else None
    if not m or path is None:
        raise HTTPException(404, "文件不存在")
    assert_can_access_material(db, user, m)
    return FileResponse(path, filename=stored_filename(m.file_path) or path.name)
