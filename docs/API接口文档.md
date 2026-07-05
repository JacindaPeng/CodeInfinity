# API 接口文档

> Base URL: `/api`  
> 鉴权：除注册/登录外均需 `Authorization: Bearer <token>`  
> 流式接口返回 `text/event-stream`

## 一、认证与用户

### POST /api/auth/register
注册新用户。
```json
// req
{ "username": "student1", "password": "123456", "role": "student", "display_name": "学生1" }
// 201
{ "id": 4, "username": "student1", "role": "student", "display_name": "学生1", "created_at": "..." }
```

### POST /api/auth/login
登录获取 JWT。
```json
// req
{ "username": "admin", "password": "admin123" }
// 200
{ "access_token": "eyJ...", "token_type": "bearer", "user": { "id": 1, ... } }
```

### GET /api/users/me
返回当前用户信息。

## 二、大模型配置

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /api/llm-configs | 全部 | 列出所有配置 |
| GET | /api/llm-configs/providers | 全部 | 列出可选提供商 |
| POST | /api/llm-configs | teacher/admin | 新增配置 |
| PUT | /api/llm-configs/{id} | teacher/admin | 修改配置 |
| DELETE | /api/llm-configs/{id} | teacher/admin | 删除配置 |

```json
// POST req
{ "provider": "deepseek", "api_key": "sk-...", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "is_default": true }
```

## 三、智能体

### GET /api/agents
列出智能体。

### GET /api/agents/{id}
智能体详情。

### POST /api/agents/course/ask （SSE 流式）
课程问答 RAG。
```
event: recommend
data: {"recommendations":[{...}]}

event: message
data: {"text":"AVL树是..."}

event: message
data: [DONE]
```
```json
// req
{ "question": "什么是AVL树？", "chapter_id": 6, "history": [{"role":"user","content":"..."},{"role":"assistant","content":"..."}] }
```

## 四、大模型对话

### POST /api/chat/stream （SSE 流式）
通用大模型对话。
```json
// req
{ "messages": [{"role":"user","content":"你好"}], "provider": null, "config_id": null }
```

## 五、资料管理

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /api/materials | 全部 | 列表（可按 chapter_id 过滤） |
| POST | /api/materials/upload | teacher/admin | multipart 上传并自动索引 |
| DELETE | /api/materials/{id} | teacher/admin | 删除资料与索引 |
| POST | /api/materials/reindex | teacher/admin | 全量重建索引 |
| GET | /api/materials/stats | 全部 | 索引片段统计 |
| GET | /api/materials/file/{id} | 全部 | 获取原始文件（视频/PDF） |

**上传表单字段**：`chapter_id` (int), `title` (str), `file` (File)
返回：`{ "ok": true, "material_id": 5, "chunks": 18 }`

## 六、章节

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/chapters | 章节列表 |
| GET | /api/chapters/{id} | 章节详情（含知识点与资料） |
| GET | /api/chapters/{id}/progress | 当前用户该章进度 |
| GET | /api/chapters/progress/all | 当前用户全部章节进度 |

## 七、资源推荐

### POST /api/recommend
```json
// req
{ "question": "AVL 树平衡调整", "chapter_id": 6, "k": 5 }
// 200
[{
  "material_id": 3, "type": "video", "title": "AVL树讲解",
  "chapter_id": 6, "chapter_title": "第六章 树与AVL树",
  "score": 0.82, "video_start_sec": 120, "video_end_sec": 150,
  "page": null, "file_url": "/api/materials/file/3"
}]
```

## 八、章节考核

### 学生端

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/exams/start | 开始考核，生成试卷 |
| POST | /api/exams/{id}/answer | 暂存单题答案 |
| POST | /api/exams/{id}/submit | 提交并评分生成报告 |
| GET | /api/exams/{id} | 获取试卷（提交后含答案与评分） |
| GET | /api/exams/{id}/report | 获取评价报告 |
| GET | /api/exams/history/mine | 我的考核历史 |

```json
// POST /api/exams/start
{ "chapter_id": 6 }
// 200
{ "exam_id": 12, "questions": [{ "idx": 1, "source": "bank", "type": "选择题", "stem": "...", "options": ["A. ...","B. ...","C. ...","D. ..."], "user_answer": "" }] }

// POST /api/exams/{id}/answer
{ "idx": 1, "answer": "A" }

// POST /api/exams/{id}/submit
// 200
{ "exam_id": 12, "report_id": 8 }

// GET /api/exams/{id}/report
{
  "exam_id": 12, "chapter_id": 6,
  "dimensions": { "知识掌握情况": 85, "基础概念掌握": 90, "综合分析能力": 75, "建议复习知识点": 60 },
  "summary": "...",
  "suggestions": "...",
  "questions": [{ "idx":1, "type":"选择题", "stem":"...", "user_answer":"A", "correct_answer":"B", "is_correct": false, "ai_score": 0, "ai_feedback": "..." }]
}
```

### 教师端

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/exams/config/{chapter_id} | 获取章节考核配置 |
| POST | /api/exams/config | 保存章节考核配置 |
| GET | /api/exams/bank?chapter_id= | 题库列表 |
| POST | /api/exams/bank | 新增题目 |
| PUT | /api/exams/bank/{id} | 修改题目 |
| DELETE | /api/exams/bank/{id} | 删除题目 |
| GET | /api/exams/knowledge-points/{chapter_id} | 章节知识点列表 |

```json
// POST /api/exams/config
{ "chapter_id": 6, "config": { "选择题": 2, "判断题": 2, "简答题": 2, "knowledge_points": ["AVL树","平衡调整"] } }

// POST /api/exams/bank
{ "chapter_id": 6, "kp_id": 1, "type": "选择题", "stem": "AVL树是？", "options": ["A. 二叉搜索树","B. ..."], "answer": "A", "analysis": "..." }
```

## 九、调用日志

### GET /api/logs
教师/管理员查看调用历史。

| 参数 | 说明 |
|------|------|
| endpoint | 按 endpoint 过滤 |
| page | 页码，默认 1 |
| size | 每页，默认 20 |

返回：`{ "total": 100, "page": 1, "size": 20, "items": [...] }`

## 十、错误响应

所有错误返回统一格式：
```json
{ "detail": "错误描述" }
```

常见状态码：
- 400：业务校验失败
- 401：未认证或 token 过期
- 403：权限不足
- 404：资源不存在
- 500：服务器内部错误
