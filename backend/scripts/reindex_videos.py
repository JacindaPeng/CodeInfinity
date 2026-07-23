"""仅重建视频资料索引（换 Whisper 模型 / 切片参数后使用）。

用法（在 backend 目录）:
  python -m scripts.reindex_videos
  python -m scripts.reindex_videos --material-id 12
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 保证可从 backend/ 直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.models import Material  # noqa: E402
from app.services.indexer import index_material, reindex_videos  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Reindex video materials with current Whisper settings")
    parser.add_argument("--material-id", type=int, default=None, help="只重建指定 material")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.material_id is not None:
            m = db.get(Material, args.material_id)
            if not m or m.type != "video":
                print(f"material {args.material_id} not found or not video")
                sys.exit(1)
            n = index_material(db, m)
            print(f"reindexed material {m.id}: {n} chunks")
            return
        result = reindex_videos(db)
        print(f"done: {result}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
