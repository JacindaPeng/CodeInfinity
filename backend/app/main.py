"""FastAPI 入口：CORS、路由挂载、健康检查。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    agents,
    auth,
    chapters,
    chat,
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
    # 启动时确保上传目录存在
    from pathlib import Path
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
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
    exams.router,                                               # 阶段4
]
for _r in _routers:
    app.include_router(_r, prefix="/api")
