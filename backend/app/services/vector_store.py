"""Chroma 向量库封装：持久化、嵌入、增删查。

优先使用 chromadb 默认 ONNX embedding（all-MiniLM-L6-v2）。
Docker/国内网络常无法下载该模型：当模型不可用时自动回退到本地哈希向量，
保证「上传资料 / 生成章节 / 索引」可完成（检索质量弱于 ONNX，但可演示）。
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from pathlib import Path
from typing import Any

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings

from ..config import settings

logger = logging.getLogger(__name__)

_client: chromadb.api.ClientAPI | None = None
_collection: chromadb.api.Collection | None = None
_embedding_mode: str | None = None


class HashBagEmbeddingFunction(EmbeddingFunction):
    """无外网依赖的确定性向量，用于 Docker 离线回退。"""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def __call__(self, input: Documents) -> Embeddings:
        out: list[list[float]] = []
        for text in input:
            vec = [0.0] * self.dim
            tokens = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", (text or "").lower())
            if not tokens:
                tokens = ["_empty_"]
            for t in tokens:
                h = int(hashlib.md5(t.encode("utf-8")).hexdigest(), 16)
                idx = h % self.dim
                sign = 1.0 if (h >> 8) & 1 else -1.0
                vec[idx] += sign
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


def _onnx_model_ready() -> bool:
    model_dir = Path.home() / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2"
    if not model_dir.is_dir():
        return False
    markers = ("model.onnx", "tokenizer.json", "config.json")
    if any((model_dir / m).exists() for m in markers):
        return True
    for child in model_dir.iterdir():
        if child.is_dir() and any((child / m).exists() for m in markers):
            return True
    return False


def _resolve_embedding() -> tuple[Any, str]:
    """返回 (embedding_function|None, mode)。None 表示交给 chromadb 默认 ONNX。"""
    mode = (os.environ.get("CHROMA_EMBEDDING_MODE") or "auto").strip().lower()
    if mode in ("hash", "offline", "local"):
        return HashBagEmbeddingFunction(), "hash"
    if mode == "onnx":
        return None, "onnx"
    # auto：仅当本地已有完整 ONNX 时用默认；否则不触发下载，直接哈希回退
    if _onnx_model_ready():
        return None, "onnx"
    logger.warning(
        "Chroma ONNX model not found locally; using offline hash embedding. "
        "Set CHROMA_EMBEDDING_MODE=onnx after caching the model under ~/.cache/chroma."
    )
    return HashBagEmbeddingFunction(), "hash"


def get_client() -> chromadb.api.ClientAPI:
    global _client
    if _client is None:
        Path(settings.chroma_path).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=settings.chroma_path)
    return _client


def embedding_mode() -> str:
    global _embedding_mode
    if _embedding_mode is None:
        _, _embedding_mode = _resolve_embedding()
    return _embedding_mode


def _collection_name() -> str:
    return "course_knowledge" if embedding_mode() == "onnx" else "course_knowledge_hash"


def get_collection() -> chromadb.api.Collection:
    global _collection, _embedding_mode
    if _collection is not None:
        return _collection
    ef, mode = _resolve_embedding()
    _embedding_mode = mode
    name = "course_knowledge" if mode == "onnx" else "course_knowledge_hash"
    kwargs: dict[str, Any] = {"name": name, "metadata": {"hnsw:space": "cosine", "embed": mode}}
    if ef is not None:
        kwargs["embedding_function"] = ef
    _collection = get_client().get_or_create_collection(**kwargs)
    return _collection


def reset_collection() -> None:
    """删除并重建集合（全量重建索引用）。"""
    global _collection
    name = _collection_name()
    try:
        get_client().delete_collection(name)
    except Exception:
        pass
    _collection = None
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
    global _client, _collection, _embedding_mode
    _client = None
    _collection = None
    _embedding_mode = None


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
