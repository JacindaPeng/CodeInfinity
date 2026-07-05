"""Chroma 向量库封装：持久化、嵌入、增删查。

使用 sentence-transformers (all-MiniLM-L6-v2) 本地嵌入，无需 API。
"""
from __future__ import annotations

from typing import Any

import chromadb
from chromadb.utils import embedding_functions

from ..config import settings

COLLECTION = "course_knowledge"

_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

_client: chromadb.api.ClientAPI | None = None


def get_client() -> chromadb.api.ClientAPI:
    global _client
    if _client is None:
        from pathlib import Path
        Path(settings.chroma_path).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=settings.chroma_path)
    return _client


def get_collection() -> chromadb.api.Collection:
    return get_client().get_or_create_collection(
        name=COLLECTION, embedding_function=_ef, metadata={"hnsw:space": "cosine"}
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
    res = get_collection().query(query_texts=[question], n_results=n_results, where=where)
    docs = res["documents"][0] if res["documents"] else []
    metas = res["metadatas"][0] if res["metadatas"] else []
    dists = res["distances"][0] if res["distances"] else []
    return [{"document": d, "metadata": m, "distance": dist}
            for d, m, dist in zip(docs, metas, dists)]


def count() -> int:
    try:
        return get_collection().count()
    except Exception:
        return 0
