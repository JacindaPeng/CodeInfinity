"""在 Windows 等环境下自动定位 ffmpeg 并加入进程 PATH。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def _candidate_dirs() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "")
    return [
        Path(local) / "Microsoft" / "WinGet" / "Links",
        Path("C:/ffmpeg/bin"),
        Path("C:/Program Files/ffmpeg/bin"),
        Path(program_files) / "ffmpeg" / "bin",
    ]


def resolve_ffmpeg(explicit: str | None = None) -> str | None:
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return str(p)
    found = shutil.which("ffmpeg")
    if found:
        return found
    for d in _candidate_dirs():
        exe = d / "ffmpeg.exe"
        if exe.is_file():
            return str(exe)
    return None


def ensure_ffmpeg_on_path(explicit: str | None = None) -> str | None:
    exe = resolve_ffmpeg(explicit)
    if not exe:
        return None
    dir_path = str(Path(exe).parent)
    path = os.environ.get("PATH", "")
    parts = [p.lower() for p in path.split(os.pathsep) if p]
    if dir_path.lower() not in parts:
        os.environ["PATH"] = dir_path + os.pathsep + path
    return exe
