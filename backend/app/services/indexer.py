"""索引编排：把一个 Material 解析、切片、写入 Chroma 与 video_segments。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Material, VideoSegment
from . import doc_parser, vector_store, video_service


def index_material(db: Session, material: Material) -> int:
    """索引单个资料，返回写入 chunk 数。"""
    base_meta = {
        "material_id": material.id,
        "chapter_id": material.chapter_id,
        "type": material.type,
        "title": material.title,
    }

    if material.type == "video":
        result = video_service.process_video(material.file_path, base_meta)
        # 写 video_segments
        for s in result["segments"]:
            db.add(VideoSegment(
                video_id=material.id,
                start_sec=int(s["start"]), end_sec=int(s["end"]),
                subtitle_text=s["text"],
            ))
        chunks = result["chunks"]
    else:
        chunks = doc_parser.parse_document(material.file_path, base_meta)

    if not chunks:
        return 0

    docs = [c for c, _ in chunks]
    metas = [m for _, m in chunks]
    ids = [f"m{material.id}-c{i}" for i in range(len(chunks))]
    vector_store.add_chunks(docs, metas, ids)
    db.commit()
    return len(chunks)


def reindex_all(db: Session) -> dict:
    """全量重建：清空集合，重新索引所有资料。"""
    vector_store.reset_collection()
    total = 0
    materials = db.query(Material).all()
    for m in materials:
        try:
            total += index_material(db, m)
        except Exception as e:
            # 单个失败不阻断整体
            print(f"[reindex] material {m.id} failed: {e}")
    return {"materials": len(materials), "chunks": total}
