"""索引编排：把一个 Material 解析、切片、写入 Chroma 与 video_segments。"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Chapter, Material, VideoSegment
from . import doc_parser, vector_store, video_service
from .storage_paths import resolve_upload_path


def _get_chapter_title(db: Session, chapter_id: int) -> str:
    ch = db.get(Chapter, chapter_id)
    return ch.title if ch else ""


def _material_disk_path(material: Material) -> str:
    path = resolve_upload_path(material.file_path)
    if path is None:
        raise FileNotFoundError(f"资料文件不存在: {material.file_path}")
    return str(path)


def index_material(db: Session, material: Material) -> int:
    """索引单个资料，返回写入 chunk 数。"""
    chapter = db.get(Chapter, material.chapter_id)
    chapter_title = chapter.title if chapter else ""
    course_id = chapter.course_id if chapter else ""
    base_meta = {
        "material_id": material.id,
        "chapter_id": material.chapter_id,
        "course_id": course_id,
        "class_id": material.class_id or "",
        "agent_id": material.agent_id or "",
        "chapter_title": chapter_title,
        "type": material.type,
        "title": material.title,
    }
    disk_path = _material_disk_path(material)

    if material.type == "video":
        # 先清理旧 video_segments
        db.execute(delete(VideoSegment).where(VideoSegment.video_id == material.id))
        result = video_service.process_video(disk_path, base_meta)
        for s in result["segments"]:
            db.add(VideoSegment(
                video_id=material.id,
                start_sec=int(s["start"]), end_sec=int(s["end"]),
                subtitle_text=s["text"],
            ))
        chunks = result["chunks"]
    else:
        chunks = doc_parser.parse_document(disk_path, base_meta)

    if not chunks:
        db.commit()
        return 0

    # 清理旧 chunks（避免重复 reindex 堆积）
    vector_store.delete_by_material(material.id)

    docs = [c for c, _ in chunks]
    metas = [m for _, m in chunks]
    ids = [f"m{material.id}-c{i}" for i in range(len(chunks))]
    vector_store.add_chunks(docs, metas, ids)
    db.commit()
    if course_id:
        from .agent_service import maybe_activate_course_agent
        maybe_activate_course_agent(db, int(course_id))
    return len(chunks)


def _build_page_offset_map(pages_text: list[str], splits: list[dict] | None = None) -> dict[int, int]:
    """构建 PDF页码→印刷页码 映射。

    方法：从目录页解析每章的印刷页码，结合章节拆分器的 PDF 起始页，
    用线性插值计算每页的印刷页码。
    """
    import re

    # 1. 从目录页解析 章节order_idx → 印刷页码
    toc_pages: dict[int, int] = {}  # order_idx → printed_page
    chap_pat = re.compile(r'第\s*(\d+)\s*章')

    for text in pages_text:
        if not text:
            continue
        # 只看目录页（含点引导符）
        dot_count = text[:800].count("…") + text[:800].count("．．") + text[:800].count("...")
        if dot_count < 3:
            continue
        # 在整个目录页文本中查找所有 "第N章" 出现的位置
        for m in chap_pat.finditer(text):
            order = int(m.group(1))
            if order in toc_pages:
                continue
            # 在章节标题后 100 字符内查找页码数字
            after = text[m.end():m.end() + 100]
            # 清理点引导符后提取数字
            clean = re.sub(r'[\.．…\s]+', ' ', after)
            nums = re.findall(r'\b(\d{1,3})\b', clean)
            for n in nums:
                val = int(n)
                if 1 <= val <= 500:
                    toc_pages[order] = val
                    break

    # 2. 结合 splits（章节拆分结果：order_idx → PDF起始页）
    if splits is None:
        return {}

    known: list[tuple[int, int]] = []  # [(pdf_page, printed_page), ...]
    for sp in splits:
        order = sp.get("order_idx", -1)
        pdf_start = sp.get("start_page", 0)
        if order in toc_pages and pdf_start > 0:
            known.append((pdf_start, toc_pages[order]))

    if not known:
        return {}

    known.sort(key=lambda x: x[0])

    # 3. 线性插值构建完整映射
    offset_map: dict[int, int] = {}
    for idx in range(len(known)):
        pdf_p, printed_p = known[idx]
        if idx == 0 and pdf_p > 1:
            offset = pdf_p - printed_p
            for p in range(1, pdf_p):
                offset_map[p] = max(1, p - offset)
        offset_map[pdf_p] = printed_p
        if idx + 1 < len(known):
            next_pdf, next_printed = known[idx + 1]
            for p in range(pdf_p + 1, next_pdf):
                ratio = (p - pdf_p) / (next_pdf - pdf_p)
                interpolated = round(printed_p + ratio * (next_printed - printed_p))
                offset_map[p] = max(1, interpolated)
        else:
            offset = pdf_p - printed_p
            for p in range(pdf_p + 1, len(pages_text) + 1):
                offset_map[p] = max(1, p - offset)

    return offset_map


def index_pdf_pages(
    db: Session, material: Material, pages_text: list[str], page_range: tuple[int, int],
    offset_map: dict[int, int] | None = None,
) -> int:
    """索引 PDF 指定页码区间（1-based）到 material。
    直接使用 PDF 页码（不做印刷页码转换，避免 OCR 误差）。
    """
    chapter_title = _get_chapter_title(db, material.chapter_id)
    chapter = db.get(Chapter, material.chapter_id)
    course_id = chapter.course_id if chapter else ""
    base_meta = {
        "material_id": material.id,
        "chapter_id": material.chapter_id,
        "course_id": course_id,
        "class_id": material.class_id or "",
        "agent_id": material.agent_id or "",
        "chapter_title": chapter_title,
        "type": "pdf",
        "title": material.title,
    }

    start, end = page_range
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=600, chunk_overlap=80,
        separators=["\n\n", "\n", "。", "；", " ", ""],
    )

    chunks: list[tuple[str, dict]] = []
    for page_no in range(start, end + 1):
        if page_no - 1 >= len(pages_text):
            break
        text = pages_text[page_no - 1] or ""
        if not text.strip():
            continue
        meta = dict(base_meta)
        meta["page"] = page_no  # 直接用 PDF 页码
        for i, piece in enumerate(splitter.split_text(text)):
            if piece.strip():
                meta["chunk_idx"] = i
                chunks.append((piece, dict(meta)))

    if not chunks:
        return 0

    vector_store.delete_by_material(material.id)
    docs = [c for c, _ in chunks]
    metas = [m for _, m in chunks]
    ids = [f"m{material.id}-p{start}-c{i}" for i in range(len(chunks))]
    vector_store.add_chunks(docs, metas, ids)
    db.commit()
    if course_id:
        from .agent_service import maybe_activate_course_agent
        maybe_activate_course_agent(db, int(course_id))
    return len(chunks)


def reindex_all(db: Session, class_ids: list[int] | None = None) -> dict:
    """重建索引。class_ids 为 None 时全量重建；否则仅重建所管班级资料。"""
    q = select(Material)
    if class_ids is not None:
        if not class_ids:
            return {"materials": 0, "chunks": 0}
        q = q.where(Material.class_id.in_(class_ids))
    materials = list(db.scalars(q).all())

    if class_ids is None:
        vector_store.reset_collection()
        db.execute(delete(VideoSegment))
        db.commit()
    else:
        for m in materials:
            vector_store.delete_by_material(m.id)
            db.execute(delete(VideoSegment).where(VideoSegment.video_id == m.id))
        db.commit()

    total = 0
    for m in materials:
        try:
            total += index_material(db, m)
        except Exception as e:
            print(f"[reindex] material {m.id} failed: {e}")
    return {"materials": len(materials), "chunks": total}


def reindex_videos(db: Session, class_ids: list[int] | None = None) -> dict:
    """仅重建视频资料（换 Whisper 模型后用）。保留 PDF 索引不动。"""
    q = select(Material).where(Material.type == "video")
    if class_ids is not None:
        if not class_ids:
            return {"materials": 0, "chunks": 0}
        q = q.where(Material.class_id.in_(class_ids))
    materials = list(db.scalars(q).all())

    total = 0
    for m in materials:
        try:
            total += index_material(db, m)
        except Exception as e:
            print(f"[reindex-videos] material {m.id} failed: {e}")
    return {"materials": len(materials), "chunks": total}
