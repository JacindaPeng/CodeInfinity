"""上传文件路径解析：兼容本机 Windows 绝对路径与 Docker /data/uploads。"""
from __future__ import annotations

from pathlib import Path

from ..config import settings


def stored_filename(stored: str | None) -> str:
    """从任意风格路径取出文件名（Linux 下 Path 无法解析反斜杠）。"""
    if not stored:
        return ""
    return Path(str(stored).replace("\\", "/")).name


def resolve_upload_path(stored: str | None) -> Path | None:
    """将数据库中的 file_path 解析为当前环境可读的实际文件。

    优先原路径；不存在时用 UPLOAD_DIR + 文件名回退（覆盖 Docker 挂载场景）。
    """
    if not stored:
        return None
    raw = str(stored).strip()
    if not raw:
        return None

    direct = Path(raw)
    try:
        if direct.is_file():
            return direct
    except OSError:
        pass

    # Windows 路径在 Linux 上不能直接用 Path(raw)
    name = stored_filename(raw)
    if not name:
        return None
    cand = Path(settings.upload_dir) / name
    try:
        if cand.is_file():
            return cand
    except OSError:
        pass
    return None


def portable_upload_path(filename: str) -> str:
    """写入数据库用的路径：始终落在当前 UPLOAD_DIR 下。"""
    return str((Path(settings.upload_dir) / stored_filename(filename)).resolve())
