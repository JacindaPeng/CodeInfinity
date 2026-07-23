"""ORM 模型：覆盖全部业务表。"""
from datetime import datetime
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="student")  # student/teacher/admin
    display_name: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_classes.id"), nullable=True)
    feedback_credit: Mapped[int] = mapped_column(Integer, default=0)  # 判卷反馈信誉分
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    progress: Mapped[list["ChapterProgress"]] = relationship(back_populates="user")
    exams: Mapped[list["Exam"]] = relationship(back_populates="user")
    teaching_class: Mapped["TeachingClass | None"] = relationship(
        back_populates="students",
        foreign_keys=[class_id],
    )
    managed_classes: Mapped[list["ClassTeacher"]] = relationship(
        back_populates="teacher",
        foreign_keys="ClassTeacher.user_id",
    )
    class_enrollments: Mapped[list["ClassEnrollment"]] = relationship(back_populates="user")


class TeachingClass(Base):
    __tablename__ = "teaching_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    invite_code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    students: Mapped[list["User"]] = relationship(
        back_populates="teaching_class",
        foreign_keys="User.class_id",
    )
    teachers: Mapped[list["ClassTeacher"]] = relationship(back_populates="teaching_class", cascade="all, delete-orphan")
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    course: Mapped["Course | None"] = relationship(foreign_keys=[course_id])
    enrollments: Mapped[list["ClassEnrollment"]] = relationship(back_populates="teaching_class", cascade="all, delete-orphan")


class ClassEnrollment(Base):
    """学生选课：每门课程最多加入一个班级。"""
    __tablename__ = "class_enrollments"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_student_course"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="class_enrollments")
    teaching_class: Mapped["TeachingClass"] = relationship(back_populates="enrollments")
    course: Mapped["Course"] = relationship()


class ClassTeacher(Base):
    __tablename__ = "class_teachers"

    class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)

    teaching_class: Mapped["TeachingClass"] = relationship(back_populates="teachers")
    teacher: Mapped["User"] = relationship(
        back_populates="managed_classes",
        foreign_keys=[user_id],
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")

    chapters: Mapped[list["Chapter"]] = relationship(back_populates="course", cascade="all, delete-orphan")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(128))
    order_idx: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")

    course: Mapped["Course"] = relationship(back_populates="chapters")
    knowledge_points: Mapped[list["KnowledgePoint"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")
    materials: Mapped[list["Material"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")
    exam_configs: Mapped[list["ExamConfig"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_classes.id"), nullable=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128))

    chapter: Mapped["Chapter"] = relationship(back_populates="knowledge_points")


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_classes.id"), nullable=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(16))  # ppt/pdf/video/word
    title: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512))
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    chapter: Mapped["Chapter"] = relationship(back_populates="materials")
    teaching_class: Mapped["TeachingClass | None"] = relationship(foreign_keys=[class_id])
    agent: Mapped["Agent | None"] = relationship(back_populates="materials")
    video_segments: Mapped[list["VideoSegment"]] = relationship(back_populates="material", cascade="all, delete-orphan")


class VideoSegment(Base):
    __tablename__ = "video_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    start_sec: Mapped[int] = mapped_column(Integer)
    end_sec: Mapped[int] = mapped_column(Integer)
    subtitle_text: Mapped[str] = mapped_column(Text, default="")

    material: Mapped["Material"] = relationship(back_populates="video_segments")


class ExamConfig(Base):
    __tablename__ = "exam_configs"
    __table_args__ = (
        UniqueConstraint("chapter_id", "class_id", "agent_id", name="uq_exam_config_chapter_class_agent"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_classes.id"), nullable=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # {"选择题": 2, "判断题": 2, "简答题": 2, "knowledge_points": ["AVL树", ...]}
    max_attempts: Mapped[int] = mapped_column(Integer, default=0)  # 0=无限次

    chapter: Mapped["Chapter"] = relationship(back_populates="exam_configs")


class QuestionBank(Base):
    __tablename__ = "question_bank"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_classes.id"), nullable=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    kp_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_points.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(32))  # 选择题/判断题/简答题/填空题/...
    stem: Mapped[str] = mapped_column(Text)
    options_json: Mapped[dict] = mapped_column(JSON, default=list)  # ["A. ...", ...]
    answer: Mapped[str] = mapped_column(Text)
    analysis: Mapped[str] = mapped_column(Text, default="")
    # 考卷导入溯源
    source_import_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("exam_import_jobs.id"), nullable=True
    )
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 综合题：额外章节/知识点标签（主章节仍用 chapter_id/kp_id）
    extra_chapter_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    extra_kp_names_json: Mapped[list] = mapped_column(JSON, default=list)


class ExamImportJob(Base):
    """往年考卷导入任务。"""
    __tablename__ = "exam_import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # uploaded/parsing/classifying/reviewing/publishing/completed/failed
    status: Mapped[str] = mapped_column(String(16), default="uploaded")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    target_class_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str] = mapped_column(Text, default="")
    stats_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    files: Mapped[list["ExamImportFile"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    candidates: Mapped[list["QuestionCandidate"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class ExamImportFile(Base):
    """导入任务关联文件：试卷 / 答案。"""
    __tablename__ = "exam_import_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("exam_import_jobs.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # paper / answer
    filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512))
    parse_status: Mapped[str] = mapped_column(String(16), default="pending")
    extracted_chars: Mapped[int] = mapped_column(Integer, default=0)

    job: Mapped["ExamImportJob"] = relationship(back_populates="files")


class QuestionCandidate(Base):
    """考卷拆出的候选题，待教师核实后入库。"""
    __tablename__ = "question_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("exam_import_jobs.id"), index=True)
    original_number: Mapped[str] = mapped_column(String(32), default="")
    type: Mapped[str] = mapped_column(String(32), default="简答题")
    stem: Mapped[str] = mapped_column(Text, default="")
    options_json: Mapped[list] = mapped_column(JSON, default=list)
    answer: Mapped[str] = mapped_column(Text, default="")
    analysis: Mapped[str] = mapped_column(Text, default="")
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True)
    extra_chapter_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    kp_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_points.id"), nullable=True)
    new_kp_name: Mapped[str] = mapped_column(String(128), default="")
    extra_kp_names_json: Mapped[list] = mapped_column(JSON, default=list)
    # pending / approved / rejected
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # paper / embedded / ai / manual
    answer_source: Mapped[str] = mapped_column(String(16), default="paper")
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    classification_note: Mapped[str] = mapped_column(Text, default="")
    review_note: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")

    job: Mapped["ExamImportJob"] = relationship(back_populates="candidates")


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    status: Mapped[str] = mapped_column(String(16), default="ongoing")  # ongoing/submitted
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="exams")
    questions: Mapped[list["ExamQuestion"]] = relationship(back_populates="exam", cascade="all, delete-orphan", order_by="ExamQuestion.idx")
    report: Mapped["ExamReport | None"] = relationship(back_populates="exam", uselist=False, cascade="all, delete-orphan")


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    idx: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(8), default="bank")  # bank/llm
    type: Mapped[str] = mapped_column(String(16))
    stem: Mapped[str] = mapped_column(Text)
    options_json: Mapped[dict] = mapped_column(JSON, default=list)
    correct_answer: Mapped[str] = mapped_column(Text, default="")
    user_answer: Mapped[str] = mapped_column(Text, default="")
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_score: Mapped[float | None] = mapped_column(nullable=True)
    ai_feedback: Mapped[str] = mapped_column(Text, default="")
    analysis: Mapped[str] = mapped_column(Text, default="")
    kp_name: Mapped[str] = mapped_column(String(128), default="")

    exam: Mapped["Exam"] = relationship(back_populates="questions")


class ExamReport(Base):
    __tablename__ = "exam_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), unique=True)
    dimensions_json: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    suggestions: Mapped[str] = mapped_column(Text, default="")
    total_score: Mapped[float | None] = mapped_column(nullable=True)
    weak_points: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    exam: Mapped["Exam"] = relationship(back_populates="report")


class ExamQuestionFollowup(Base):
    """考核报告：单题追问记录。"""
    __tablename__ = "exam_question_followups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    question_idx: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    recommendations_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExamGradingFeedback(Base):
    """学生对 AI 判卷结果的反馈。"""
    __tablename__ = "exam_grading_feedbacks"
    __table_args__ = (UniqueConstraint("exam_question_id", "user_id", name="uq_grading_fb_per_q"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_question_id: Mapped[int] = mapped_column(ForeignKey("exam_questions.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    verdict: Mapped[str] = mapped_column(String(16))  # agree / disagree
    comment: Mapped[str] = mapped_column(Text, default="")
    reward_delta: Mapped[int] = mapped_column(Integer, default=0)
    teacher_confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExamIntervention(Base):
    """判卷争议：教师介入申请。"""
    __tablename__ = "exam_interventions"
    __table_args__ = (
        UniqueConstraint("exam_id", "question_idx", "student_id", name="uq_exam_iv_per_question"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    question_idx: Mapped[int] = mapped_column(Integer)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id"))
    trigger: Mapped[str] = mapped_column(String(16))  # auto / manual
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/resolved/dismissed
    student_message: Mapped[str] = mapped_column(Text, default="")
    teacher_response: Mapped[str] = mapped_column(Text, default="")
    context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_score: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChapterProgress(Base):
    __tablename__ = "chapter_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    status: Mapped[str] = mapped_column(String(16), default="未完成")  # 未完成/已完成/待学习
    last_exam_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped["User"] = relationship(back_populates="progress")


class LLMConfig(Base):
    __tablename__ = "llm_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))  # deepseek/qwen/openai/moonshot/...
    api_key: Mapped[str] = mapped_column(String(255))
    base_url: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(64))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_agent_owner_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    intro: Mapped[str] = mapped_column(Text, default="")
    endpoint: Mapped[str] = mapped_column(String(128), default="")  # 调用入口标识
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    slug: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / planned
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    shared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id])
    source_agent: Mapped["Agent | None"] = relationship(remote_side="Agent.id", foreign_keys=[source_agent_id])
    class_bindings: Mapped[list["AgentClass"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    materials: Mapped[list["Material"]] = relationship(back_populates="agent")


class AgentClass(Base):
    __tablename__ = "agent_classes"
    __table_args__ = (UniqueConstraint("agent_id", "class_id", name="uq_agent_class"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id"))
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    agent: Mapped["Agent"] = relationship(back_populates="class_bindings")
    teaching_class: Mapped["TeachingClass"] = relationship()


class CallLog(Base):
    __tablename__ = "call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    endpoint: Mapped[str] = mapped_column(String(128))
    req_summary: Mapped[str] = mapped_column(Text, default="")
    resp_summary: Mapped[str] = mapped_column(Text, default="")
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    model_name: Mapped[str] = mapped_column(String(128), default="")
    answer_full: Mapped[str] = mapped_column(Text, default="")
    attachments_json: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class KnowledgeSource(Base):
    """白名单 RSS / 内容源（不做站点重爬）。"""
    __tablename__ = "knowledge_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str] = mapped_column(String(512), default="")
    rss_url: Mapped[str] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tags: Mapped[str] = mapped_column(String(255), default="")  # 逗号分隔，如 python,c,general
    resource_type: Mapped[str] = mapped_column(String(16), default="article")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    articles: Mapped[list["KnowledgeArticle"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class KnowledgeArticle(Base):
    """从白名单源拉取的候选文章。"""
    __tablename__ = "knowledge_articles"
    __table_args__ = (UniqueConstraint("url", name="uq_knowledge_article_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("knowledge_sources.id"))
    url: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(512), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    keywords_json: Mapped[list] = mapped_column(JSON, default=list)
    resource_type: Mapped[str] = mapped_column(String(16), default="article")

    source: Mapped["KnowledgeSource"] = relationship(back_populates="articles")
    pushes: Mapped[list["KnowledgePush"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )


class KnowledgePush(Base):
    """发给学生的知识推送。"""
    __tablename__ = "knowledge_pushes"
    __table_args__ = (
        UniqueConstraint("user_id", "article_id", name="uq_knowledge_push_user_article"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("knowledge_articles.id"))
    reason: Mapped[str] = mapped_column(Text, default="")
    kp_names_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="unread")  # unread/read/dismissed
    pushed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    article: Mapped["KnowledgeArticle"] = relationship(back_populates="pushes")


class ClassChatMessage(Base):
    """班级群聊消息：普通发言 / 话题 / 话题回复。"""
    __tablename__ = "class_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    msg_type: Mapped[str] = mapped_column(String(16), default="text")  # text/topic/topic_reply
    content: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("class_chat_messages.id"), nullable=True, index=True
    )
    knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    sender: Mapped["User"] = relationship(foreign_keys=[sender_id])
    knowledge_point: Mapped["KnowledgePoint | None"] = relationship(foreign_keys=[knowledge_point_id])


class ClassChatDm(Base):
    """班级内师生私信（仅双方可见）。"""
    __tablename__ = "class_chat_dms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sender: Mapped["User"] = relationship(foreign_keys=[sender_id])
    receiver: Mapped["User"] = relationship(foreign_keys=[receiver_id])


class ClassChatRead(Base):
    """用户在某班级某频道的已读游标。channel: group | topic:{id} | dm:{peer_id}"""
    __tablename__ = "class_chat_reads"
    __table_args__ = (
        UniqueConstraint("user_id", "class_id", "channel", name="uq_class_chat_read"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id"), index=True)
    channel: Mapped[str] = mapped_column(String(64), default="group")
    last_read_message_id: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SmsCode(Base):
    """短信验证码：注册 / 登录场景。"""
    __tablename__ = "sms_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    scene: Mapped[str] = mapped_column(String(16), default="login")  # register | login
    code_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
