# API 接口文档

> Base URL：`/api`  
> 鉴权：除标注「公开」外，请求头 `Authorization: Bearer <token>`  
> 流式接口：`Content-Type: text/event-stream`  
> 交互式文档：启动后端后访问 `http://127.0.0.1:8000/docs`（以 OpenAPI 为准）  
> 健康检查（无前缀）：`GET /health` → `{"status":"ok"}`

角色依赖：`require_role("student"|"teacher"|"admin")`；未写明则登录用户即可（部分接口内部再校验归属）。

---

## 一、认证 `/auth`（公开）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /auth/sms/send | 发验证码 `{ phone, scene: "register"\|"login" }` |
| POST | /auth/register | 注册：username、password、role、phone、code、display_name? |
| POST | /auth/login | 密码登录 → `{ access_token, user }` |
| POST | /auth/login/phone | 手机号+验证码登录 |

开发模式 `SMS_DEV_MODE=1` 时 send 可能带 `dev_hint`，验证码为 `SMS_DEV_CODE`。

## 二、用户 `/users`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /users/me | 当前用户（手机号脱敏） |

## 三、大模型配置 `/llm-configs`

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /llm-configs/providers | 登录 | 可选提供商 |
| GET | /llm-configs | 登录 | 列表 |
| POST / PUT / DELETE | /llm-configs[/{id}] | admin | 增删改 |

## 四、智能体 `/agents`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /agents | 当前用户可见智能体 |
| GET | /agents/{id} | 详情 |
| GET | /agents/course/history | 课程问答历史 |
| POST | /agents/course/ask | **SSE** 课程 RAG 问答 |

SSE 事件示例：`recommend`（推荐列表）、`message`（增量文本）、结束标记。

## 五、教师智能体 `/teacher/agents`（teacher）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /teacher/agents | 我拥有的 |
| GET | /teacher/agents/shared | 他人共享列表 |
| POST | /teacher/agents | 创建 |
| PUT / DELETE | /teacher/agents/{id} | 更新 / 删除 |
| PUT | /teacher/agents/{id}/classes | 绑定班级 |
| POST | /teacher/agents/{id}/share | 共享 |
| POST | /teacher/agents/adopt/{source_id} | 采纳副本 |
| GET | /teacher/agents/{id}/adopters | 采纳者 |

## 六、通用对话 `/chat`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /chat/stream | **SSE** 通用对话 |
| GET | /chat/history | 历史 |
| POST | /chat/parse-file | 解析上传文件 |
| POST | /chat/transcribe | 语音转写 |
| GET | /chat/voice-status | 语音能力状态 |
| GET | /chat/attachments/{file_id} | 附件 |

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

## 八、资料 `/materials`

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /materials | 登录 | 列表（作用域过滤） |
| GET | /materials/stats | 登录 | 索引统计 |
| GET | /materials/file/{id} | 登录 | 下载/预览 |
| POST | /materials/upload | teacher/admin | 上传单文件 |
| POST | /materials/upload-textbook | teacher/admin | 教材上传拆章 |
| POST | /materials/upload-courseware-batch | teacher/admin | 课件批量 |
| DELETE | /materials/{id} | teacher/admin | 删除 |
| POST | /materials/reindex | teacher/admin | 重建索引 |
| POST | /materials/reindex-videos | teacher/admin | 仅视频重索引 |
| POST | /materials/re-split-textbook | teacher/admin | 教材重拆 |

## 九、推荐 `/recommend`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /recommend | 按问题/章节生成资源推荐 |

## 十、考核 `/exams`

### 学生侧

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /exams/start | 开始某章考核 |
| POST | /exams/{id}/answer | 提交单题答案 |
| POST | /exams/{id}/submit | 交卷并评分 |
| GET | /exams/{id} | 试卷详情 |
| GET | /exams/{id}/report | 报告 |
| POST | /exams/{id}/regenerate-report | 重生成报告 |
| GET | /exams/history/mine | 我的历史 |
| GET | /exams/attempts/{chapter_id} | 某章尝试次数 |
| POST | /exams/{id}/questions/{idx}/ask | 单题追问 |
| GET | /exams/{id}/questions/{idx}/followups | 追问记录 |
| POST | /exams/{id}/questions/{idx}/grading-feedback | 判卷反馈 |
| POST | /exams/{id}/questions/{idx}/intervention | 申请介入 |
| GET | /exams/{id}/questions/{idx}/intervention | 查看介入 |
| GET | /exams/{id}/feedback-meta | 反馈元信息 |

### 知识点与题库（teacher/admin）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST/PUT/DELETE | /exams/knowledge-points... | 知识点 CRUD / 建议 |
| GET/POST/PUT/DELETE | /exams/bank... | 题库 CRUD |
| GET/POST | /exams/config... | 考核配置 |

### 教师侧

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /exams/teacher/all | 班级学生试卷 |
| GET | /exams/teacher/all/{id}/report | 报告 |
| GET | /exams/teacher/students | 学生列表 |
| GET | /exams/teacher/class-progress | 班级进度 |
| GET/PUT | /exams/teacher/interventions... | 介入列表与处理 |
| GET | /exams/teacher/interventions/pending-count | 待处理数 |

## 十一、考卷导入 `/exam-imports`（teacher/admin）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /exam-imports | 创建导入任务（上传卷/答案） |
| GET | /exam-imports | 任务列表 |
| GET | /exam-imports/{job_id} | 任务详情 |
| GET | /exam-imports/{job_id}/candidates | 候选题 |
| PUT | /exam-imports/{job_id}/candidates/{cid} | 编辑候选题 |
| POST | /exam-imports/{job_id}/candidates/bulk-review | 批量审核 |
| POST | /exam-imports/{job_id}/publish | 发布入库 |
| POST | /exam-imports/{job_id}/retry | 失败重试 |

## 十二、班级 `/classes`

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /classes/my | 学生 | 我加入的班 |
| POST | /classes/join / leave | 学生 | 邀请码加入 / 退出 |
| GET | /classes/mine | teacher | 我管理的班 |
| POST / PUT / DELETE | /classes[/{id}] | teacher | CRUD |
| POST | /classes/{id}/regenerate-code | teacher | 新邀请码 |
| GET/PUT | /classes/{id}/agents | teacher | 绑定智能体 |
| * | /classes/{id}/students... | teacher | 学生增删查 |
| * | /classes/{id}/teachers... | teacher | 协作教师 |

## 十三、课程群聊 `/classes/{class_id}/chat`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | .../messages | 群消息 |
| GET/POST | .../topics、.../topics/{id}/replies | 话题与回复 |
| GET | .../knowledge-points、teachers、students | 辅助列表 |
| GET/POST | .../dms | 私信 |
| POST | .../read | 上报已读 |
| GET | .../unread | 未读数 |

## 十四、知识推送 `/knowledge-push`

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /knowledge-push/today | 登录 | 今日推送 |
| GET | /knowledge-push/unread-count | 登录 | 未读数 |
| POST | /knowledge-push/{id}/read \| dismiss | 登录 | 已读 / 忽略 |
| GET | /knowledge-push/weak-points | 登录 | 薄弱点 |
| POST | /knowledge-push/run | student | 手动跑一轮 |
| GET/POST/PUT | /knowledge-push/sources... | admin | 内容源 |
| POST | /knowledge-push/sources/import-bestblogs | admin | 导入预设源 |
| POST | /knowledge-push/fetch | admin | 拉取文章 |
| GET | /knowledge-push/admin/stats \| records | admin | 统计与记录 |
| DELETE | /knowledge-push/admin/records | admin | 清理记录 |

## 十五、调用日志 `/logs`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /logs | teacher（本人相关） |

## 十六、管理端 `/admin`（admin）

| 前缀 | 说明 |
|------|------|
| /admin/users | 用户 CRUD、重置密码 |
| /admin/classes | 全站班级 |
| /admin/exams... | 全站考核与报告 |
| /admin/ai-feedback... | 判卷反馈概览与记录 |
| /admin/logs | 全站调用日志 |
| /admin/agents | 智能体 CRUD |

---

实现细节与请求体字段以 `backend/app/schemas` 及 Swagger 为准。前端封装见 `frontend/src/api/`。
