"""FastAPI 入口：CORS、路由挂载、健康检查。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    admin,
    agents,
    auth,
    chapters,
    chat,
    classes,
    exams,
    llm,
    logs,
    materials,
    recommend,
    users,
)
from .config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    from pathlib import Path
    from scripts.init_db import (
        backfill_resource_class_ids,
        migrate_call_logs_answer_full,
        migrate_call_logs_attachments_json,
        migrate_call_logs_model_name,
        migrate_materials_class_id,
        migrate_question_bank_class_id,
        migrate_exam_configs_class_id,
        migrate_knowledge_points_class_id,
        migrate_agents_extend,
        migrate_users_class_id,
    )

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.upload_dir).parent.joinpath("chat_attachments").mkdir(parents=True, exist_ok=True)
    from .utils.ffmpeg_path import ensure_ffmpeg_on_path

    ensure_ffmpeg_on_path(settings.ffmpeg_path or None)
    migrate_users_class_id()
    migrate_call_logs_model_name()
    migrate_call_logs_answer_full()
    migrate_call_logs_attachments_json()
    migrate_materials_class_id()
    migrate_question_bank_class_id()
    migrate_exam_configs_class_id()
    migrate_knowledge_points_class_id()
    migrate_agents_extend()
    backfill_resource_class_ids()
    yield


app = FastAPI(
    title="C语言程序设计课程智能体 API",
    version="0.1.0",
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
    exams.router, classes.router, admin.router,                   # 阶段4/班级/管理
]
for _r in _routers:
    app.include_router(_r, prefix="/api")
