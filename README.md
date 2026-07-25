# CodeInfinity · 课程智能体平台

基于 Vue 3 + FastAPI + SQLite + Chroma 的多课程智能体 Web 系统。以《C 语言程序设计》为默认种子课程，支持教师自建/共享课程智能体、班级教学、RAG 问答、章节考核与知识推送。

产品入口页：`/welcome`（品牌名 **CodeInfinity**）。

---

## 提交物对照（验收清单）

| 要求 | 本仓库位置 | 状态 |
|------|------------|------|
| （1）前端 Vue 源码 | `frontend/` | ✅ |
| （1）后端 Python 源码 | `backend/` | ✅ |
| （2）SQLite 数据库 | 运行后生成 `data/course.db`（`init_db` / Docker 启动自动建库） | ✅ |
| （3）系统设计 | [docs/系统设计.md](docs/系统设计.md) | ✅ |
| （3）功能说明 | [docs/功能说明.md](docs/功能说明.md) | ✅ |
| （3）数据结构设计 | [docs/数据结构设计.md](docs/数据结构设计.md) | ✅ |
| （3）API 接口文档 | [docs/API接口文档.md](docs/API接口文档.md)（运行中见 `/docs` Swagger） | ✅ |
| （3）课程设计报告（可选汇总） | `docs/专业方向课程设计报告.docx` | ✅ |
| （4）演示视频 ≥10 分钟 | 口播稿见 `docs/演示视频/演示视频逐字稿.docx`，成品视频放入 `docs/演示视频/` | ⚠️ 按稿录制后提交 |
| （5）README 部署说明 | 本文档 | ✅ |
| （5）`docker-compose up` 一键启动 | 根目录 `docker-compose.yml` | ✅ |

---

## 核心能力

| 能力 | 说明 |
|------|------|
| 课程 RAG 问答 | 从 PPT / PDF / Word / 视频字幕检索，SSE 流式回答 |
| 学习资源推荐 | 问答后推荐资料；视频命中可跳转时间戳 |
| 章节考核 | 题库 + LLM 组卷 → 自动评分 → 多维度报告；支持判卷反馈与教师介入 |
| 班级与选课 | 邀请码建班、学生按课程加入班级、班级绑定智能体 |
| 教师智能体 | 创建 / 共享 / 采纳；资料与考核按智能体隔离 |
| 课程群聊 | 班级群消息、话题、师生私信 |
| 知识推送 | 按薄弱知识点从白名单 RSS 日推（可选 Bing 搜索） |
| 考卷导入 | 上传往年卷 PDF，拆题审核后入库 |
| 认证 | 用户名密码登录；新注册需手机号 + 短信验证码（开发模式固定码 / 生产走阿里云 PNVS） |

## 技术栈

| 模块 | 技术 |
|------|------|
| 前端 | Vue 3 + Vite + TypeScript + Element Plus + Pinia + Vue Router + ECharts |
| 后端 | Python + FastAPI + SQLAlchemy 2 + Pydantic v2 + SSE |
| 数据库 | SQLite |
| 向量库 | Chroma（Docker 默认离线 Hash embedding；本机可 ONNX MiniLM） |
| RAG | langchain-text-splitters 切分 + Chroma 检索 |
| LLM | DeepSeek（默认）/ Qwen / OpenAI·Gemini·Claude（兼容中转）/ Moonshot / 智谱 |
| 文档解析 | pdfplumber / python-pptx / python-docx |
| 视频 ASR | ffmpeg + openai-whisper（可选依赖，Docker 镜像不含） |
| 短信 | 阿里云号码认证 PNVS（`SMS_DEV_MODE=1` 时不真发） |
| 部署 | Docker Compose + nginx |

## 目录结构

```
专业课程设计/
├── backend/                 # FastAPI（venv、install.bat、dev.bat）
├── frontend/                # Vue3 SPA
├── data/                    # 运行时：course.db / chroma / uploads（自动生成）
├── docs/                    # 系统设计、功能、数据结构、API、演示口播稿
│   └── 演示视频/            # 逐字稿；演示成品视频放此处
├── PL_Course/               # 课程原始资料（C / C++ / Python / SQL）
├── docker-compose.yml
├── .env.example             # Docker / 部署用环境变量模板
├── 小学期课程实践项目说明书(1).docx
└── README.md                # 本文档（部署说明）
```

---

## Docker 一键部署（验收推荐）

### 环境要求

- 已安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)（含 Compose V2）
- 可用的大模型 API Key（默认 DeepSeek）
- 建议预留磁盘与内存：镜像构建与 Chroma 初始化可能需要数分钟

### 步骤

```bash
# 1. 进入项目根目录，准备环境变量
cp .env.example .env
# 编辑 .env，至少填写：
#   DEEPSEEK_API_KEY=sk-...
#   JWT_SECRET=请换成足够长的随机串

# 2. 一键构建并启动
docker compose up -d --build

# 3. 查看状态
docker compose ps
curl http://localhost/health
```

| 入口 | 地址 |
|------|------|
| 前端 | http://localhost |
| API 健康检查 | http://localhost/health |
| Swagger 接口文档 | http://localhost/docs 或 http://localhost:8000/docs |
| 后端直连 | http://localhost:8000 |

数据持久化在 `./data`（SQLite、Chroma、上传文件）。容器默认 `SMS_DEV_MODE=1`，验证码固定为 `123456`（不会真发短信）。

停止：

```bash
docker compose down
```

仅重建后端：

```bash
docker compose build backend
docker compose up -d
```

### 向量检索模式（Chroma）

| 环境变量 | 说明 |
|----------|------|
| `CHROMA_EMBEDDING_MODE=hash` | **Docker 默认**。离线哈希向量，无需下载模型，保证一键验收 |
| `CHROMA_EMBEDDING_MODE=auto` | 本机代码默认。已有 ONNX 缓存则用 ONNX，否则 hash |
| `CHROMA_EMBEDDING_MODE=onnx` | 强制 ONNX MiniLM（检索质量更好；需模型缓存） |

可选：挂载 `./data/chroma_onnx_cache` 持久化 ONNX 缓存；或设置 `CHROMA_ONNX_MODEL_URL` 后改为 `onnx`/`auto`。切换模式后如检索异常，请在资料管理中「重建索引」。

### 常见问题

**1）构建时报 `auth.docker.io` / `failed to fetch oauth token`（国内访问 Docker Hub 超时）**  
本仓库 Dockerfile 已改用 `docker.m.daocloud.io` 镜像代理。也可在 Docker Desktop → Settings → Docker Engine 增加：

```json
{
  "registry-mirrors": ["https://docker.m.daocloud.io"]
}
```

Apply & Restart 后再执行 `docker compose up -d --build`。

**2）视频 ASR**  
当前镜像**不装 ffmpeg / whisper / torch**（体积过大易拖垮构建），以保证 `docker compose up` 能稳定验收核心功能。视频转写请用本机 `backend\dev.bat`（已装 ffmpeg + whisper）演示。

**3）上次构建把 Docker 搞崩（Bus error / EOF）**  
先重启 Docker Desktop，再执行：

```bash
docker compose build backend
docker compose up -d
```

**4）真发短信**  
在**根目录** `.env` 设置 `SMS_DEV_MODE=0` 并填写 `ALIYUN_*`（见 `.env.example`），再：

```bash
docker compose up -d --force-recreate backend
```

---

## 本地开发（Windows）

### 后端

```bat
cd backend
python -m venv venv
venv\Scripts\activate
install.bat
copy .env.example .env
REM 编辑 .env：至少填 DEEPSEEK_API_KEY；短信默认 SMS_DEV_MODE=1
python -m scripts.init_db
dev.bat
```

- API：http://127.0.0.1:8000  
- Swagger：http://127.0.0.1:8000/docs  

可选视频转写：`pip install -r requirements_video.txt`

### 前端

```bat
cd frontend
npm install
npm run dev
```

浏览器：http://localhost:5173（Vite 已将 `/api` 代理到 8000）

### 默认账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | admin123 |
| 教师 | teacher | teacher123 |
| 学生 | student | student123 |

新用户注册需手机号 + 验证码；开发模式验证码为 `123456`。

---

## 接口核对要点（验收）

1. 启动后打开 Swagger：`/docs`，确认存在认证、智能体问答、资料、考核、班级等路由。  
2. 冒烟：`POST /api/auth/login` → `GET /api/users/me` → `GET /api/agents`。  
3. 课程问答为 **SSE**：`POST /api/agents/course/ask`。  
4. 完整清单见 [docs/API接口文档.md](docs/API接口文档.md)。  

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [docs/系统设计.md](docs/系统设计.md) | 架构、模块、技术选型、RAG/权限设计 |
| [docs/功能说明.md](docs/功能说明.md) | 角色功能、业务流程、权限矩阵 |
| [docs/数据结构设计.md](docs/数据结构设计.md) | SQLite 表、Chroma 元数据、文件路径 |
| [docs/API接口文档.md](docs/API接口文档.md) | REST / SSE 接口一览 |
| [docs/演示视频/演示视频逐字稿.docx](docs/演示视频/演示视频逐字稿.docx) | ≥10 分钟演示口播稿 |
| [docs/专业方向课程设计报告.docx](docs/专业方向课程设计报告.docx) | 正式报告汇总（如有） |
| [小学期课程实践项目说明书(1).docx](小学期课程实践项目说明书(1).docx) | 课程统一项目要求 |

---

## 短信（可选生产）

开发/Docker 默认不真发短信。若需真发：开通 [号码认证 · 短信认证](https://dypns.console.aliyun.com/functions)，RAM 授权 `AliyunDypnsFullAccess`，在 `backend/.env`（或根目录 `.env`）设置 `SMS_DEV_MODE=0` 与 PNVS 参数（见 `.env.example`）。密钥勿提交仓库。
