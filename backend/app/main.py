"""FastAPI 入口：CORS、路由挂载、健康检查。"""
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    admin,
    agents,
    auth,
    chapters,
    chat,
    class_chat,
    classes,
    courses,
    exam_imports,
    exams,
    knowledge_push,
    llm,
    logs,
    materials,
    recommend,
    teacher_agents,
    users,
)
from .config import settings

# Windows 下 asyncio 默认 Proactor 有时会导致 Ctrl+C 后事件循环无法干净退出
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    from pathlib import Path
    from scripts.init_db import run_all_migrations

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.upload_dir).parent.joinpath("chat_attachments").mkdir(parents=True, exist_ok=True)
    from .utils.ffmpeg_path import ensure_ffmpeg_on_path

    ensure_ffmpeg_on_path(settings.ffmpeg_path or None)
    # 迁移由 dev.bat 启动前执行；lifespan 内默认不跑，避免热重载/SQLite 锁导致卡死
    if os.environ.get("RUN_STARTUP_MIGRATIONS") == "1":
        run_all_migrations()
    from .services.knowledge_push_scheduler import (
        start_knowledge_push_scheduler,
        stop_knowledge_push_scheduler,
    )

    start_knowledge_push_scheduler()
    try:
        yield
    finally:
        stop_knowledge_push_scheduler()
        from .database import shutdown_db
        from .services.vector_store import shutdown_client

        shutdown_client()
        shutdown_db()


app = FastAPI(
    title="CodeInfinity 课程智能体 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


# 挂载路由
_routers = [
    auth.router, users.router,
    llm.router, agents.router, logs.router, chat.router,        # 阶段1
    materials.router, chapters.router, recommend.router,        # 阶段2/3
    exams.router, exam_imports.router, classes.router, admin.router, courses.router, teacher_agents.router,
    knowledge_push.router, class_chat.router,
]
for _r in _routers:
    app.include_router(_r, prefix="/api")
