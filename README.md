# C语言程序设计课程智能体

基于 Vue3 + FastAPI + SQLite + Chroma + LangChain 构建的《C语言程序设计》课程智能体 Web 系统，提供课程 RAG 问答、学习资源推荐、章节考核自动评价三大核心功能。

## 功能

- **用户与系统管理**：注册/登录/JWT、大模型配置、智能体管理、调用日志
- **课程问答**：基于 RAG 从 PPT/PDF/Word/视频字幕中检索并流式回答
- **学习资源推荐**：根据当前章节/问题推荐 PPT、PDF、视频（含时间戳精准跳转）
- **章节考核（重点）**：教师配置题型与数量 → 题库+LLM 动态生成试卷 → 学生逐题作答 → 自动评分与维度报告
- **创新扩展**：视频时间精准定位、自适应学习路径（规划中）

## 技术栈

| 模块 | 技术 |
|------|------|
| 前端 | Vue3 + Vite + Element Plus + Pinia + Vue Router |
| 后端 | Python + FastAPI + SQLAlchemy + Pydantic v2 |
| 数据库 | SQLite |
| 向量库 | Chroma |
| RAG | LangChain |
| LLM | DeepSeek（默认）/ OpenAI / Qwen，可切换 |
| 文档解析 | pdfplumber / python-pptx / python-docx |
| 视频处理 | ffmpeg + openai-whisper |
| 部署 | Docker + docker-compose |

## 目录结构

```
专业课程设计/
├── backend/        # FastAPI 后端
├── frontend/       # Vue3 前端
├── data/           # 运行时持久化（sqlite / chroma / uploads）
├── docs/           # 项目文档
├── docker-compose.yml
└── README.md
```

## 本地开发

### 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
cp .env.example .env            # 填入 DEEPSEEK_API_KEY 等
python -m scripts.init_db       # 建表 + 注入种子数据
uvicorn app.main:app --reload --port 8000
```

默认账号：`admin/admin123`、`teacher/teacher123`、`student/student123`

### 前端

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

## Docker 一键部署

```bash
cp .env.example .env            # 填入 DEEPSEEK_API_KEY
docker-compose up -d --build
```

- 前端：http://localhost
- 后端 API：http://localhost:8000/docs
- Swagger 文档：http://localhost:8000/docs

数据持久化在 `./data` 目录（SQLite、Chroma、上传文件）。

## 文档

详见 `docs/` 目录：
- `系统设计.md`
- `功能说明.md`
- `数据结构设计.md`
- `API接口文档.md`
