# API 接口文档

> 对应《小学期课程实践项目说明书》提交物（3）项目文档 · API 接口文档  
> Base URL：`/api`  
> 鉴权：除标注「公开」外，请求头 `Authorization: Bearer <token>`  
> 流式接口：`Content-Type: text/event-stream`（SSE）  
> 交互式文档：启动后访问 `/docs`（Swagger，以 OpenAPI 为准）  
> 健康检查（无前缀）：`GET /health` → `{"status":"ok"}`

角色依赖：`require_role("student"|"teacher"|"admin")`；未写明则登录用户即可（部分接口内部再校验归属）。  
请求/响应字段细节以 `backend/app/schemas` 及运行中 Swagger 为准。前端封装见 `frontend/src/api/index.ts`。

---

## 约定说明

| 项 | 说明 |
|----|------|
| 成功 | 多数接口返回 JSON；创建类 `201` |
| 失败 | FastAPI 标准 `{"detail": "..."}` |
| 分页 | 部分列表支持 `skip`/`limit` 或等价查询参数 |
| SSE | 事件行以 `data:` 开头；含 `message` / `recommend` 等类型 |

### 登录示例

```http
POST /api/auth/login
Content-Type: application/json

{"username":"teacher","password":"teacher123"}
```

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": {"id": 2, "username": "teacher", "role": "teacher", ...}
}
```

后续请求：

```http
Authorization: Bearer <jwt>
```

---

## 一、认证 `/auth`（公开）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /auth/sms/send | 发验证码 `{ phone, scene: "register"\|"login" }` |
| POST | /auth/register | 注册：username、password、role、phone、code、display_name? |
| POST | /auth/login | 密码登录 → `{ access_token, user }` |
| POST | /auth/login/phone | 手机号 + 验证码登录 |

开发模式 `SMS_DEV_MODE=1` 时 send 可能带 `dev_hint`，验证码为 `SMS_DEV_CODE`（默认 `123456`）。

---

## 二、用户 `/users`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /users/me | 当前用户（手机号脱敏） |

---

## 三、大模型配置 `/llm-configs`

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /llm-configs/providers | 登录 | 可选提供商列表 |
| GET | /llm-configs | 登录 | 已配置列表 |
| POST | /llm-configs | admin | 新增 |
| PUT | /llm-configs/{id} | admin | 更新 |
| DELETE | /llm-configs/{id} | admin | 删除 |

---

## 四、智能体 `/agents`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /agents | 当前用户可见智能体 |
| GET | /agents/{id} | 详情 |
| GET | /agents/course/history | 课程问答历史（可按 agent 过滤） |
| POST | /agents/course/ask | **SSE** 课程 RAG 问答 |

### 课程问答（SSE）请求体（摘要）

```json
{
  "question": "什么是指针？",
  "agent_id": 1,
  "chapter_id": null
}
```

典型事件：

| 事件用途 | 说明 |
|----------|------|
| recommend | 推荐资源列表（PPT/PDF/视频及时间戳） |
| message | 增量回答文本 |
| 结束标记 | 流结束 |

---

## 五、教师智能体 `/teacher/agents`（teacher）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /teacher/agents | 我拥有的 |
| GET | /teacher/agents/shared | 他人共享列表 |
| POST | /teacher/agents | 创建（名称、简介、课程、状态等） |
| PUT | /teacher/agents/{id} | 更新 |
| DELETE | /teacher/agents/{id} | 删除 |
| PUT | /teacher/agents/{id}/classes | 绑定班级 |
| POST | /teacher/agents/{id}/share | 共享到广场 |
| POST | /teacher/agents/adopt/{source_id} | 采纳副本 |
| GET | /teacher/agents/{id}/adopters | 采纳者列表 |

---

## 六、通用对话 `/chat`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /chat/stream | **SSE** 通用大模型对话 |
| GET | /chat/history | 历史会话 |
| POST | /chat/parse-file | 解析上传文件 |
| POST | /chat/transcribe | 语音转写 |
| GET | /chat/voice-status | 语音能力是否可用 |
| GET | /chat/attachments/{file_id} | 附件下载 |

---

## 七、课程与章节

### `/courses`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /courses | 课程列表 |
| POST | /courses | teacher/admin 创建 |

### `/chapters`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /chapters | 章节列表（可按课程/智能体） |
| GET | /chapters/{id} | 详情 |
| GET | /chapters/{id}/progress | 单章进度 |
| GET | /chapters/progress/all | 全部进度 |
| POST | /chapters/custom | teacher/admin 自定义章 |
| POST | /chapters/reset-course | teacher/admin 重置课程章节 |

---

## 八、资料 `/materials`

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /materials | 登录 | 列表（作用域过滤） |
| GET | /materials/stats | 登录 | 索引统计（含 embedding 模式相关信息） |
| GET | /materials/file/{id} | 登录 | 下载/预览 |
| POST | /materials/upload | teacher/admin | 上传单文件（multipart） |
| POST | /materials/upload-textbook | teacher/admin | 教材上传并拆章 |
| POST | /materials/upload-courseware-batch | teacher/admin | 课件批量上传 |
| DELETE | /materials/{id} | teacher/admin | 删除 |
| POST | /materials/reindex | teacher/admin | 重建向量索引 |
| POST | /materials/reindex-videos | teacher/admin | 仅视频重索引 |
| POST | /materials/re-split-textbook | teacher/admin | 教材重新拆章 |

上传字段通常含：file、chapter_id、可选 class_id / agent_id。文件路径经 `storage_paths` 写入当前 `UPLOAD_DIR`。

---

## 九、推荐 `/recommend`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /recommend | 按问题/章节生成资源推荐（非流式） |

---

## 十、考核 `/exams`

### 学生侧

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /exams/start | 开始某章考核 `{ chapter_id, agent_id? }` |
| POST | /exams/{id}/answer | 提交单题答案 |
| POST | /exams/{id}/submit | 交卷并评分 |
| GET | /exams/{id} | 试卷详情 |
| GET | /exams/{id}/report | 学习报告 |
| POST | /exams/{id}/regenerate-report | 重生成报告 |
| GET | /exams/history/mine | 我的历史 |
| GET | /exams/attempts/{chapter_id} | 某章已用次数 |
| POST | /exams/{id}/questions/{idx}/ask | 单题追问 |
| GET | /exams/{id}/questions/{idx}/followups | 追问记录 |
| POST | /exams/{id}/questions/{idx}/grading-feedback | 判卷反馈 agree/disagree |
| POST | /exams/{id}/questions/{idx}/intervention | 申请教师介入 |
| GET | /exams/{id}/questions/{idx}/intervention | 查看介入状态 |
| GET | /exams/{id}/feedback-meta | 反馈元信息 |

### 知识点与题库（teacher/admin）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /exams/knowledge-points/{chapter_id} | 知识点列表 |
| GET | /exams/knowledge-points/{chapter_id}/suggest | 建议知识点 |
| POST | /exams/knowledge-points | 新增 |
| PUT | /exams/knowledge-points/{kp_id} | 更新 |
| DELETE | /exams/knowledge-points/{kp_id} | 删除 |
| GET | /exams/bank | 题库列表 |
| POST | /exams/bank | 新增题目 |
| PUT | /exams/bank/{qid} | 更新 |
| DELETE | /exams/bank/{qid} | 删除 |
| GET | /exams/config/{chapter_id} | 读取考核配置 |
| POST | /exams/config | 保存考核配置 |

### 教师侧

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /exams/teacher/all | 班级学生试卷 |
| GET | /exams/teacher/all/{id}/report | 报告 |
| GET | /exams/teacher/all/{id}/questions/{idx}/followups | 追问（教师查看） |
| POST | /exams/teacher/all/{id}/questions/{idx}/grading-feedback | 教师侧反馈确认 |
| GET | /exams/teacher/students | 学生列表 |
| GET | /exams/teacher/class-progress | 班级章节进度 |
| GET | /exams/teacher/interventions | 介入列表 |
| GET | /exams/teacher/interventions/pending-count | 待处理数 |
| GET | /exams/teacher/interventions/{iv_id} | 介入详情 |
| PUT | /exams/teacher/interventions/{iv_id} | 处理介入（裁定分数等） |

---

## 十一、考卷导入 `/exam-imports`（teacher/admin）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /exam-imports | 创建导入任务（上传卷/答案 multipart） |
| GET | /exam-imports | 任务列表 |
| GET | /exam-imports/{job_id} | 任务详情 |
| GET | /exam-imports/{job_id}/candidates | 候选题列表 |
| PUT | /exam-imports/{job_id}/candidates/{cid} | 编辑候选题 |
| POST | /exam-imports/{job_id}/candidates/bulk-review | 批量审核 |
| POST | /exam-imports/{job_id}/publish | 发布入库题库 |
| POST | /exam-imports/{job_id}/retry | 失败重试 |

---

## 十二、班级 `/classes`

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /classes/my | 学生 | 我加入的班 |
| POST | /classes/join | 学生 | 邀请码加入 |
| POST | /classes/leave | 学生 | 退出班级 |
| GET | /classes/mine | teacher | 我管理的班 |
| POST | /classes | teacher | 创建 |
| PUT | /classes/{id} | teacher | 更新名称等 |
| DELETE | /classes/{id} | teacher | 删除 |
| POST | /classes/{id}/regenerate-code | teacher | 刷新邀请码 |
| GET | /classes/{id}/agents | teacher | 已绑定智能体 |
| PUT | /classes/{id}/agents | teacher | 设置绑定智能体 |
| GET | /classes/{id}/students | teacher | 班级学生 |
| GET | /classes/{id}/students/available | teacher | 可添加学生 |
| POST | /classes/{id}/students | teacher | 添加学生 |
| DELETE | /classes/{id}/students/{sid} | teacher | 移除学生 |
| GET | /classes/{id}/teachers | teacher | 协作教师 |
| GET | /classes/{id}/teachers/available | teacher | 可添加教师 |
| POST | /classes/{id}/teachers | teacher | 添加协作教师 |
| DELETE | /classes/{id}/teachers/{tid} | teacher | 移除协作教师 |

---

## 十三、课程群聊 `/classes/{class_id}/chat`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | .../messages | 群消息列表 / 发送 |
| GET/POST | .../topics | 话题列表 / 发起 |
| GET/POST | .../topics/{id}/replies | 话题回复 |
| GET | .../knowledge-points | 可选关联知识点 |
| GET | .../teachers、.../students | 成员列表 |
| GET/POST | .../dms | 私信 |
| POST | .../read | 上报已读 |
| GET | .../unread | 未读数 |

---

## 十四、知识推送 `/knowledge-push`

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /knowledge-push/today | 登录 | 今日推送 |
| GET | /knowledge-push/unread-count | 登录 | 未读数 |
| POST | /knowledge-push/{id}/read | 登录 | 标记已读 |
| POST | /knowledge-push/{id}/dismiss | 登录 | 忽略 |
| GET | /knowledge-push/weak-points | 登录 | 薄弱知识点 |
| POST | /knowledge-push/run | student | 手动跑一轮推送 |
| GET | /knowledge-push/sources | admin | 内容源列表 |
| POST | /knowledge-push/sources | admin | 新增源 |
| PUT | /knowledge-push/sources/{id} | admin | 更新源 |
| POST | /knowledge-push/sources/import-bestblogs | admin | 导入预设源 |
| POST | /knowledge-push/fetch | admin | 拉取文章 |
| GET | /knowledge-push/admin/stats | admin | 统计 |
| GET | /knowledge-push/admin/records | admin | 推送记录 |
| DELETE | /knowledge-push/admin/records | admin | 清理记录 |

---

## 十五、调用日志 `/logs`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /logs | teacher：本人相关调用记录 |

---

## 十六、管理端 `/admin`（admin）

| 前缀 | 说明 |
|------|------|
| GET/POST/PUT/DELETE /admin/users... | 用户 CRUD |
| POST /admin/users/{id}/reset-password | 重置密码 |
| GET /admin/classes | 全站班级 |
| GET /admin/exams... | 全站考核、学生列表、报告 |
| GET /admin/ai-feedback/overview\|records | 判卷反馈概览与明细 |
| GET /admin/logs | 全站调用日志 |
| GET/POST/PUT/DELETE /admin/agents... | 全站智能体 CRUD |

---

## 十七、验收冒烟清单

1. `GET /health` → `ok`  
2. `POST /api/auth/login` → 取得 token  
3. `GET /api/users/me`  
4. `GET /api/agents`  
5. `POST /api/agents/course/ask`（SSE，需有效 LLM Key 与已索引资料）  
6. 教师：`GET /api/materials`、`GET /api/exams/config/{chapter_id}`  
7. 学生：`POST /api/exams/start` → 作答 → `submit` → `GET .../report`  

完整字段与试调用请使用 Swagger：`http://localhost/docs`（Docker）或 `http://127.0.0.1:8000/docs`（本地）。
