"""预热 Chroma 默认 ONNX embedding 模型，避免首次上传资料时卡在下载。

Docker 内访问 chroma-onnx-models.s3.amazonaws.com 往往极慢，导致上传超时、章节回滚。
本脚本在容器启动时下载/校验模型到持久化缓存目录。
"""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_URL = (
    "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"
)
# 完整包约 79MB；小于该阈值视为残缺下载
MIN_TAR_BYTES = 70 * 1024 * 1024


def _cache_dir() -> Path:
    # 与 chromadb DefaultEmbeddingFunction 一致
    return Path.home() / ".cache" / "chroma" / "onnx_models" / MODEL_NAME


def _model_ready(model_dir: Path) -> bool:
    if not model_dir.is_dir():
        return False
    # 解压后常见文件
    markers = ("model.onnx", "tokenizer.json", "config.json")
    found = [p for p in markers if (model_dir / p).exists()]
    if found:
        return True
    # 有些版本解压到子目录
    for child in model_dir.iterdir():
        if child.is_dir() and any((child / m).exists() for m in markers):
            return True
    return False


def _download(url: str, dest: Path, timeout: int = 600) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    if tmp.exists():
        tmp.unlink()
    print(f"[warmup] downloading {url}", flush=True)
    print(f"[warmup] -> {dest}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "codeinfinity-warmup/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        last_log = time.time()
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            now = time.time()
            if now - last_log >= 5:
                if total:
                    pct = 100.0 * done / total
                    print(f"[warmup] {done / 1e6:.1f}/{total / 1e6:.1f} MB ({pct:.1f}%)", flush=True)
                else:
                    print(f"[warmup] {done / 1e6:.1f} MB", flush=True)
                last_log = now
    if tmp.stat().st_size < MIN_TAR_BYTES:
        size = tmp.stat().st_size
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"download too small ({size} bytes), likely truncated")
    tmp.replace(dest)


def _extract(tar_path: Path, model_dir: Path) -> None:
    print(f"[warmup] extracting {tar_path.name}", flush=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=model_dir)


def main() -> int:
    url = os.environ.get("CHROMA_ONNX_MODEL_URL", DEFAULT_URL).strip() or DEFAULT_URL
    model_dir = _cache_dir()
    model_dir.mkdir(parents=True, exist_ok=True)
    tar_path = model_dir / "onnx.tar.gz"

    if _model_ready(model_dir):
        print("[warmup] ONNX model already ready", flush=True)
        return 0

    # 残缺包清掉重下
    if tar_path.exists() and tar_path.stat().st_size < MIN_TAR_BYTES:
        print(f"[warmup] remove incomplete archive ({tar_path.stat().st_size} bytes)", flush=True)
        tar_path.unlink()

    try:
        if not tar_path.exists():
            _download(url, tar_path)
        elif tar_path.stat().st_size < MIN_TAR_BYTES:
            _download(url, tar_path)
        else:
            print(f"[warmup] reuse archive {tar_path.stat().st_size} bytes", flush=True)

        _extract(tar_path, model_dir)

        # 触发 chromadb 加载校验
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        ef = DefaultEmbeddingFunction()
        vec = ef(["warmup"])
        print(f"[warmup] embedding ok dim={len(vec[0])}", flush=True)
        return 0
    except Exception as e:
        print(f"[warmup] FAILED: {e}", flush=True)
        print(
            "[warmup] 上传教材仍可生成章节，但向量索引可能失败。"
            "可将已下载的 onnx 模型放到 data/chroma_onnx_cache 后重启容器。",
            flush=True,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
