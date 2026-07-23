"""Chroma 向量库封装：持久化、嵌入、增删查。

使用 chromadb 默认 embedding function（基于 onnxruntime 的 all-MiniLM-L6-v2 ONNX 版），
无需 sentence-transformers / transformers 额外依赖，避免 tokenizers 版本冲突。
首次使用时 chromadb 会自动下载 ONNX 模型到本地缓存。
"""
from __future__ import annotations

from typing import Any

import chromadb

from ..config import settings

COLLECTION = "course_knowledge"

_client: chromadb.api.ClientAPI | None = None


def get_client() -> chromadb.api.ClientAPI:
    global _client
    if _client is None:
        from pathlib import Path
        Path(settings.chroma_path).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=settings.chroma_path)
    return _client


def get_collection() -> chromadb.api.Collection:
    # 不传 embedding_function，使用 chromadb 默认（ONNX MiniLM-L6-V2）
    return get_client().get_or_create_collection(
        name=COLLECTION, metadata={"hnsw:space": "cosine"}
    )


def reset_collection() -> None:
    """删除并重建集合（全量重建索引用）。"""
    try:
        get_client().delete_collection(COLLECTION)
    except Exception:
        pass
    get_collection()


def add_chunks(
    chunks: list[str],
    metadatas: list[dict[str, Any]],
    ids: list[str] | None = None,
) -> None:
    if not chunks:
        return
    if ids is None:
        ids = [f"chunk-{i}-{hash(chunks[i]) & 0xFFFFFFFF}" for i in range(len(chunks))]
    # Chroma metadata 值必须是 str/int/float/bool，统一转 str
    safe_meta = [{k: (",".join(v) if isinstance(v, list) else str(v)) if v is not None else ""
                  for k, v in m.items()} for m in metadatas]
    get_collection().add(documents=chunks, metadatas=safe_meta, ids=ids)


def delete_by_material(material_id: int) -> None:
    try:
        get_collection().delete(where={"material_id": str(material_id)})
    except Exception:
        pass


def query(question: str, n_results: int = 5, where: dict | None = None) -> list[dict]:
    """检索相关 chunk。返回 [{document, metadata, distance}]。"""
    for n in (n_results, max(1, n_results // 2), 1):
        try:
            res = get_collection().query(query_texts=[question], n_results=n, where=where)
            docs = res["documents"][0] if res["documents"] else []
            metas = res["metadatas"][0] if res["metadatas"] else []
            dists = res["distances"][0] if res["distances"] else []
            return [{"document": d, "metadata": m, "distance": dist}
                    for d, m, dist in zip(docs, metas, dists)]
        except Exception:
            continue
    return []


def shutdown_client() -> None:
    """释放 Chroma 持久化客户端，避免退出时后台线程拖住进程。"""
    global _client
    _client = None


def count(class_ids: list[int] | None = None) -> int:
    try:
        col = get_collection()
        if class_ids is None:
            return col.count()
        if not class_ids:
            return 0
        if len(class_ids) == 1:
            where = {"class_id": str(class_ids[0])}
        else:
            where = {"class_id": {"$in": [str(c) for c in class_ids]}}
        return col.count(where=where)
    except Exception:
        return 0
