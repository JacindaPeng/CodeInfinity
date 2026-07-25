"""Docker 启动：若命名卷为空且宿主机 ./data/chroma 有旧索引，则拷入卷内。

Windows 绑盘上的 Chroma I/O 很慢；命名卷在 Linux 文件系统内，检索快很多。
首次迁移大库可能较久，属一次性操作。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _has_content(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    try:
        next(path.iterdir())
        return True
    except StopIteration:
        return False


def main() -> int:
    dst = Path(os.environ.get("CHROMA_PATH", "/chroma"))
    src = Path(os.environ.get("CHROMA_MIGRATE_FROM", "/data/chroma"))

    if _has_content(dst):
        print(f"[ok] chroma volume ready: {dst}", flush=True)
        return 0

    dst.mkdir(parents=True, exist_ok=True)

    if not _has_content(src):
        print(f"[ok] empty chroma at {dst} (no source at {src})", flush=True)
        return 0

    if src.resolve() == dst.resolve():
        print(f"[ok] chroma path is {dst}", flush=True)
        return 0

    print(f"[migrate] copying chroma {src} -> {dst} (first boot may take a while)...", flush=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
    print("[ok] chroma migrated to docker volume", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
